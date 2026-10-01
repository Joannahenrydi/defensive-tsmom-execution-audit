"""Risk-budgeted cross-asset portfolio backtest with soft macro exposure caps."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, linprog, minimize

from backtest.cross_asset import CrossAssetResult
from portfolio.optimizer import PortfolioCosts, estimate_costs


@dataclass(frozen=True)
class RiskBudgetConfig:
    rebalance_every: int = 5
    covariance_window: int = 126
    covariance_shrinkage: float = 0.50
    max_gross: float = 1.0
    max_name: float = 0.15
    max_turnover: float = 0.25
    max_participation: float = 0.001
    annual_volatility_cap: float = 0.10
    net_cap: float = 0.35
    max_long_gross: float | None = None
    max_short_gross: float | None = None
    liquidity_limited_cap_reduction: bool = False
    nav: float = 100_000.0
    tolerance: float = 1e-7
    max_iterations: int = 500


def _is_feasible_candidate(result, bounds, linear, volatility_constraint, tolerance):
    """Independently validate a finite SLSQP candidate when convergence is not reported."""
    if result.x is None or not np.isfinite(result.x).all():
        return False
    lower_violation = float(np.max(bounds.lb - result.x))
    upper_violation = float(np.max(result.x - bounds.ub))
    linear_violation = float(np.max(linear.A @ result.x - linear.ub))
    volatility_violation = -float(volatility_constraint(result.x))
    return max(
        lower_violation,
        upper_violation,
        linear_violation,
        volatility_violation,
    ) <= tolerance


def run_risk_budget_backtest(
    expected_return: pd.DataFrame,
    returns: pd.DataFrame,
    adv: pd.DataFrame,
    eligibility: pd.DataFrame,
    factor_loadings: pd.DataFrame,
    factor_caps: pd.Series,
    asset_sleeves: pd.Series,
    sleeve_caps: pd.Series | pd.DataFrame,
    *,
    risk_scaler: pd.Series | None = None,
    long_gross_scaler: pd.Series | None = None,
    short_gross_scaler: pd.Series | None = None,
    name_scaler: pd.DataFrame | None = None,
    config: RiskBudgetConfig | None = None,
    costs: PortfolioCosts | None = None,
) -> CrossAssetResult:
    config = config or RiskBudgetConfig()
    costs = costs or PortfolioCosts(
        commission_bps=0, half_spread_bps=1, slippage_bps=1,
        impact_coefficient=0.10, borrow_annual=0.01, calendar_days=7,
    )
    columns = returns.columns
    if not all(frame.index.equals(returns.index) and frame.columns.equals(columns)
               for frame in (expected_return, adv, eligibility)):
        raise ValueError("wide inputs must align")
    if not factor_loadings.index.equals(columns) or not asset_sleeves.index.equals(columns):
        raise ValueError("risk metadata must align")
    required_sleeves = pd.Index(asset_sleeves.unique())
    if isinstance(sleeve_caps, pd.DataFrame):
        if not sleeve_caps.index.equals(returns.index) or not required_sleeves.isin(
            sleeve_caps.columns
        ).all():
            raise ValueError("dynamic sleeve caps must align to sessions and sleeves")
        sleeve_cap_values = sleeve_caps.loc[:, required_sleeves]
    else:
        if not required_sleeves.isin(sleeve_caps.index).all():
            raise ValueError("sleeve caps must cover every sleeve")
        sleeve_cap_values = sleeve_caps.loc[required_sleeves]
    sleeve_cap_array = sleeve_cap_values.to_numpy(dtype=float)
    if not np.isfinite(sleeve_cap_array).all() or (sleeve_cap_array < 0).any():
        raise ValueError("sleeve caps must be finite and nonnegative")
    if risk_scaler is None:
        risk_scaler = pd.Series(1.0, index=returns.index)
    if not risk_scaler.index.equals(returns.index) or risk_scaler.isna().any():
        raise ValueError("risk scaler must be finite and align to sessions")
    if not np.isfinite(risk_scaler).all() or risk_scaler.le(0).any() or risk_scaler.gt(1).any():
        raise ValueError("risk scaler must be in (0, 1]")
    side_scalers = {
        "long gross scaler": long_gross_scaler,
        "short gross scaler": short_gross_scaler,
    }
    for label, side_scaler in side_scalers.items():
        if side_scaler is None:
            side_scalers[label] = pd.Series(1.0, index=returns.index)
            continue
        if not side_scaler.index.equals(returns.index) or side_scaler.isna().any():
            raise ValueError(f"{label} must be finite and align to sessions")
        if (
            not np.isfinite(side_scaler).all()
            or side_scaler.lt(0).any()
            or side_scaler.gt(1).any()
        ):
            raise ValueError(f"{label} must be in [0, 1]")
    long_gross_scaler = side_scalers["long gross scaler"]
    short_gross_scaler = side_scalers["short gross scaler"]
    if name_scaler is None:
        name_scaler = pd.DataFrame(1.0, index=returns.index, columns=columns)
    if not name_scaler.index.equals(returns.index) or not name_scaler.columns.equals(columns):
        raise ValueError("name scaler must align to sessions and assets")
    if not np.isfinite(name_scaler).all().all():
        raise ValueError("name scaler must be finite")
    if name_scaler.lt(0).any().any() or name_scaler.gt(1).any().any():
        raise ValueError("name scaler must be in [0, 1]")
    if config.max_long_gross is not None and config.max_long_gross < 0:
        raise ValueError("maximum long gross must be nonnegative")
    if config.max_short_gross is not None and config.max_short_gross < 0:
        raise ValueError("maximum short gross must be nonnegative")
    active = pd.Series(0.0, index=columns)
    pending_cost = pending_turnover = 0.0
    records, weights, rebalances = [], [], []
    last_session = None
    for offset, session in enumerate(returns.index):
        realized = returns.loc[session]
        if (active.ne(0) & realized.isna()).any():
            return CrossAssetResult(pd.DataFrame(records).set_index("session"), pd.DataFrame(weights),
                                    pd.DataFrame(rebalances), "INVALID", "MISSING_HELD_RETURN")
        gross_return = float((active * realized.fillna(0)).sum())
        days = 1 if last_session is None else max(1, (session - last_session).days)
        borrow = float(active.clip(upper=0).abs().sum()) * costs.borrow_annual * days / 365 * costs.multiplier
        net_return = gross_return - pending_cost - borrow
        records.append({"session": session, "gross_return": gross_return,
                        "transaction_cost": pending_cost, "borrow_cost": borrow,
                        "net_return": net_return, "gross": float(active.abs().sum()),
                        "net": float(active.sum()), "turnover": pending_turnover})
        weights.append(active.rename(session))
        denominator = 1 + net_return
        if denominator <= 0:
            return CrossAssetResult(pd.DataFrame(records).set_index("session"), pd.DataFrame(weights),
                                    pd.DataFrame(rebalances), "INVALID", "NONPOSITIVE_NAV")
        active = active.mul(1 + realized.fillna(0)).div(denominator)
        pending_cost = pending_turnover = 0.0
        if offset % config.rebalance_every == 0 and offset >= config.covariance_window:
            scale = float(risk_scaler.loc[session])
            long_scale = float(long_gross_scaler.loc[session])
            short_scale = float(short_gross_scaler.loc[session])
            scaled_long_cap = (
                config.max_long_gross * scale * long_scale
                if config.max_long_gross is not None
                else None
            )
            scaled_short_cap = (
                config.max_short_gross * scale * short_scale
                if config.max_short_gross is not None
                else None
            )
            session_sleeve_caps = (
                sleeve_caps.loc[session]
                if isinstance(sleeve_caps, pd.DataFrame)
                else sleeve_caps
            )
            usable = eligibility.loc[session] & expected_return.loc[session].notna() & adv.loc[session].gt(0)
            names = columns[usable]
            if len(names) < 8:
                last_session = session
                continue
            history = returns.loc[:session, names].tail(config.covariance_window)
            covariance = history.cov().to_numpy(dtype=float)
            covariance = ((1 - config.covariance_shrinkage) * covariance
                          + config.covariance_shrinkage * np.diag(np.diag(covariance)))
            alpha = expected_return.loc[session, names].to_numpy(dtype=float)
            previous = active.loc[names].to_numpy(dtype=float)
            fixed = active.drop(names)
            fixed_gross = float(fixed.abs().sum())
            fixed_net = float(fixed.sum())
            fixed_long_gross = float(fixed.clip(lower=0).sum())
            fixed_short_gross = float(fixed.clip(upper=0).abs().sum())
            factors = factor_loadings.loc[names]
            fixed_factor_exposure = factor_loadings.drop(index=names).T @ fixed
            sleeves = asset_sleeves.loc[names]
            fixed_sleeve_gross = fixed.abs().groupby(asset_sleeves.drop(index=names)).sum()
            liquidity = adv.loc[session, names].to_numpy(dtype=float)
            capacity = liquidity * config.max_participation / config.nav
            base_cost = (costs.commission_bps + costs.half_spread_bps + costs.slippage_bps) / 10_000
            weekly_borrow = costs.borrow_annual * 7 / 365 * costs.multiplier
            n = len(names)
            # x = [weights, absolute holdings, absolute trades]. Auxiliary variables make
            # every cost/exposure constraint linear; only the volatility cap is quadratic.
            objective_vector = np.r_[
                -alpha - weekly_borrow / 2,
                np.full(n, weekly_borrow / 2),
                np.full(n, base_cost * costs.multiplier),
            ]
            rows, upper = [], []

            def add(row, limit, output_rows=rows, output_upper=upper):
                output_rows.append(row)
                output_upper.append(limit)

            eye, zeros = np.eye(n), np.zeros((n, n))
            for row, limit in zip(np.hstack([eye, -eye, zeros]), np.zeros(n)):
                add(row, limit)  # w <= |w|
            for row, limit in zip(np.hstack([-eye, -eye, zeros]), np.zeros(n)):
                add(row, limit)  # -w <= |w|
            for row, limit in zip(np.hstack([eye, zeros, -eye]), previous):
                add(row, limit)  # w - previous <= |trade|
            for row, limit in zip(np.hstack([-eye, zeros, -eye]), -previous):
                add(row, limit)  # previous - w <= |trade|
            scaled_gross = config.max_gross * scale
            available_gross = scaled_gross - fixed_gross
            scaled_name = (
                config.max_name * scale
                * name_scaler.loc[session, names].to_numpy(dtype=float)
            )
            lower_name = -scaled_name.copy()
            upper_name = scaled_name.copy()
            if config.liquidity_limited_cap_reduction:
                # When the desired cap falls faster than the ADV limit permits, execute the
                # maximum feasible risk reduction and disclose the residual cap excess. This
                # preserves the hard participation constraint rather than pretending an
                # impossible liquidation occurred.
                liquidity_floor = previous - capacity
                liquidity_ceiling = previous + capacity
                forced_long = liquidity_floor > upper_name
                forced_short = liquidity_ceiling < lower_name
                lower_name[forced_long] = liquidity_floor[forced_long]
                upper_name[forced_long] = liquidity_floor[forced_long]
                lower_name[forced_short] = liquidity_ceiling[forced_short]
                upper_name[forced_short] = liquidity_ceiling[forced_short]
            holding_bound = np.maximum(np.abs(lower_name), np.abs(upper_name))
            desired_sleeve_caps = session_sleeve_caps.astype(float) * scale
            effective_sleeve_caps = desired_sleeve_caps.copy()
            effective_gross_cap = scaled_gross
            effective_net_cap = config.net_cap * scale
            effective_long_cap = scaled_long_cap
            effective_short_cap = scaled_short_cap
            if config.liquidity_limited_cap_reduction:
                reachable_lower = np.maximum(lower_name, previous - capacity)
                reachable_upper = np.minimum(upper_name, previous + capacity)
                minimum_name_gross = np.where(
                    reachable_lower > 0,
                    reachable_lower,
                    np.where(reachable_upper < 0, -reachable_upper, 0.0),
                )
                effective_gross_cap = max(
                    scaled_gross, float(minimum_name_gross.sum() + fixed_gross)
                )
                minimum_net = float(reachable_lower.sum() + fixed_net)
                maximum_net = float(reachable_upper.sum() + fixed_net)
                minimum_absolute_net = (
                    0.0
                    if minimum_net <= 0 <= maximum_net
                    else min(abs(minimum_net), abs(maximum_net))
                )
                effective_net_cap = max(effective_net_cap, minimum_absolute_net)
                if effective_long_cap is not None:
                    minimum_long = float(
                        np.maximum(reachable_lower, 0).sum() + fixed_long_gross
                    )
                    effective_long_cap = max(float(effective_long_cap), minimum_long)
                if effective_short_cap is not None:
                    minimum_short = float(
                        np.maximum(-reachable_upper, 0).sum() + fixed_short_gross
                    )
                    effective_short_cap = max(float(effective_short_cap), minimum_short)
                for sleeve in session_sleeve_caps.index:
                    mask = sleeves.eq(sleeve).to_numpy()
                    minimum_tradable_gross = float(
                        np.maximum(np.abs(previous[mask]) - capacity[mask], 0).sum()
                        + fixed_sleeve_gross.get(sleeve, 0)
                    )
                    effective_sleeve_caps.loc[sleeve] = max(
                        float(desired_sleeve_caps.loc[sleeve]), minimum_tradable_gross
                    )
            available_gross = effective_gross_cap - fixed_gross
            required_reduction = [max(0.0, np.abs(previous).sum() - max(available_gross, 0))]
            required_reduction.append(
                max(0.0, abs(previous.sum() + fixed_net) - effective_net_cap)
            )
            required_reduction.append(float(np.maximum(np.abs(previous) - scaled_name, 0).sum()))
            if config.max_long_gross is not None:
                current_long_gross = float(
                    np.maximum(previous, 0).sum() + fixed_long_gross
                )
                required_reduction.append(
                    max(0.0, current_long_gross - float(effective_long_cap))
                )
            if config.max_short_gross is not None:
                current_short_gross = float(
                    np.abs(np.minimum(previous, 0)).sum() + fixed_short_gross
                )
                required_reduction.append(
                    max(0.0, current_short_gross - float(effective_short_cap))
                )
            for factor in factors.columns:
                vector = factors[factor].to_numpy(dtype=float)
                total_exposure = vector @ previous + float(fixed_factor_exposure[factor])
                excess = max(0.0, abs(total_exposure) - float(factor_caps[factor]) * scale)
                required_reduction.append(excess / max(float(np.abs(vector).max()), 1e-12))
            for sleeve in session_sleeve_caps.index:
                mask = sleeves.eq(sleeve).to_numpy()
                required_reduction.append(
                    max(0.0, np.abs(previous[mask]).sum()
                        + float(fixed_sleeve_gross.get(sleeve, 0))
                        - float(effective_sleeve_caps.loc[sleeve]))
                )
            # Per-name cap cuts can themselves create a new net/factor/sleeve breach. The
            # ordinary turnover cap must then be relaxed by both the forced trades and the
            # smallest additional correction, otherwise individually feasible constraints
            # become jointly infeasible (for example when cash fallback closes several shorts).
            cap_target = np.clip(previous, lower_name, upper_name)
            forced_turnover = float(np.abs(cap_target - previous).sum())
            post_cap_corrections = [
                max(0.0, np.abs(cap_target).sum() + fixed_gross - effective_gross_cap),
                max(0.0, abs(cap_target.sum() + fixed_net) - effective_net_cap),
            ]
            if config.max_long_gross is not None:
                post_cap_long = float(
                    np.maximum(cap_target, 0).sum() + fixed_long_gross
                )
                post_cap_corrections.append(
                    max(0.0, post_cap_long - float(effective_long_cap))
                )
            if config.max_short_gross is not None:
                post_cap_short = float(
                    np.abs(np.minimum(cap_target, 0)).sum() + fixed_short_gross
                )
                post_cap_corrections.append(
                    max(0.0, post_cap_short - float(effective_short_cap))
                )
            for factor in factors.columns:
                vector = factors[factor].to_numpy(dtype=float)
                exposure = vector @ cap_target + float(fixed_factor_exposure[factor])
                excess = max(0.0, abs(exposure) - float(factor_caps[factor]) * scale)
                post_cap_corrections.append(
                    excess / max(float(np.abs(vector).max()), 1e-12)
                )
            for sleeve in session_sleeve_caps.index:
                mask = sleeves.eq(sleeve).to_numpy()
                post_cap_corrections.append(
                    max(0.0, np.abs(cap_target[mask]).sum()
                        + float(fixed_sleeve_gross.get(sleeve, 0))
                        - float(effective_sleeve_caps.loc[sleeve]))
                )
            required_reduction.append(forced_turnover + max(post_cap_corrections))
            # A risk-cap cut overrides the ordinary turnover cap only by the minimum
            # amount needed to restore feasibility; the resulting trades are still costed.
            turnover_limit = max(config.max_turnover, max(required_reduction) + config.tolerance)
            add(np.r_[np.zeros(n), np.ones(n), np.zeros(n)], available_gross)
            turnover_row = len(rows)
            add(np.r_[np.zeros(2 * n), np.ones(n)], turnover_limit)
            add(np.r_[np.ones(n), np.zeros(2 * n)], effective_net_cap - fixed_net)
            add(np.r_[-np.ones(n), np.zeros(2 * n)], effective_net_cap + fixed_net)
            if config.max_long_gross is not None:
                # For exact auxiliaries u=|w|, (u+w)/2 equals the long gross.
                remaining_long = float(effective_long_cap) - fixed_long_gross
                add(
                    np.r_[0.5 * np.ones(n), 0.5 * np.ones(n), np.zeros(n)],
                    remaining_long,
                )
            if config.max_short_gross is not None:
                # For exact auxiliaries u=|w|, (u-w)/2 equals the short gross.
                remaining_short = float(effective_short_cap) - fixed_short_gross
                add(
                    np.r_[-0.5 * np.ones(n), 0.5 * np.ones(n), np.zeros(n)],
                    remaining_short,
                )
            for factor in factors.columns:
                vector = factors[factor].to_numpy(dtype=float)
                cap = float(factor_caps[factor]) * scale
                fixed_exposure = float(fixed_factor_exposure[factor])
                add(np.r_[vector, np.zeros(2 * n)], cap - fixed_exposure)
                add(np.r_[-vector, np.zeros(2 * n)], cap + fixed_exposure)
            for sleeve in session_sleeve_caps.index:
                mask = sleeves.eq(sleeve).to_numpy(dtype=float)
                remaining = float(effective_sleeve_caps.loc[sleeve]) - float(
                    fixed_sleeve_gross.get(sleeve, 0)
                )
                add(np.r_[np.zeros(n), mask, np.zeros(n)], remaining)
            linear_matrix = np.vstack(rows)
            linear_upper = np.asarray(upper)
            linear = LinearConstraint(linear_matrix, -np.inf, linear_upper)

            def objective(x, vector=objective_vector):
                return float(10_000 * vector @ x)

            def objective_jac(_x, vector=objective_vector):
                return 10_000 * vector

            variance_cap = config.annual_volatility_cap ** 2 / 252

            def volatility_constraint(x, dimension=n, cov=covariance, cap=variance_cap):
                weight = x[:dimension]
                return cap - float(weight @ cov @ weight)

            def volatility_jac(x, dimension=n, cov=covariance):
                return np.r_[-2 * cov @ x[:dimension], np.zeros(2 * dimension)]

            initial_weight = np.clip(previous, lower_name, upper_name)
            if config.max_long_gross is not None:
                remaining_long = max(
                    0.0, float(effective_long_cap) - fixed_long_gross
                )
                initial_long = float(np.maximum(initial_weight, 0).sum())
                if initial_long > remaining_long and initial_long > 0:
                    positive = initial_weight > 0
                    initial_weight[positive] *= remaining_long / initial_long
            if config.max_short_gross is not None:
                remaining_short = max(
                    0.0, float(effective_short_cap) - fixed_short_gross
                )
                initial_short = float(np.abs(np.minimum(initial_weight, 0)).sum())
                if initial_short > remaining_short and initial_short > 0:
                    negative = initial_weight < 0
                    initial_weight[negative] *= remaining_short / initial_short
            initial_trade = np.abs(initial_weight - previous)
            initial = np.r_[initial_weight, np.abs(initial_weight), initial_trade]
            bounds = Bounds(
                np.r_[lower_name, np.zeros(2 * n)],
                np.r_[upper_name, holding_bound, capacity],
            )
            result = minimize(
                objective, initial, jac=objective_jac, method="SLSQP", bounds=bounds,
                constraints=[linear, {"type": "ineq", "fun": volatility_constraint,
                                      "jac": volatility_jac}],
                options={"maxiter": config.max_iterations, "ftol": 1e-9, "disp": False},
            )
            linear_fallback_reason = "NOT_RUN"
            emergency_constraint_override = False
            independently_feasible = _is_feasible_candidate(
                result, bounds, linear, volatility_constraint, config.tolerance
            )
            if not result.success and not independently_feasible:
                # HiGHS provides a deterministic feasibility/linear-objective fallback when
                # SLSQP fails at a corner created by simultaneous liquidity, factor and dynamic
                # sleeve cuts. Accept it only after the same independent volatility check.
                linear_result = linprog(
                    objective_vector,
                    A_ub=linear_matrix,
                    b_ub=linear_upper,
                    bounds=list(zip(bounds.lb, bounds.ub, strict=True)),
                    method="highs",
                )
                linear_fallback_reason = (
                    f"{linear_result.status}_{linear_result.message}"
                )
                if linear_result.success:
                    linear_candidate = OptimizeResult(
                        x=linear_result.x,
                        success=False,
                        status=-4,
                        message="independently verified HiGHS linear fallback",
                    )
                    if _is_feasible_candidate(
                        linear_candidate,
                        bounds,
                        linear,
                        volatility_constraint,
                        config.tolerance,
                    ):
                        result = linear_candidate
                        independently_feasible = True
                    else:
                        nonlinear_retry = minimize(
                            objective,
                            linear_result.x,
                            jac=objective_jac,
                            method="SLSQP",
                            bounds=bounds,
                            constraints=[
                                linear,
                                {
                                    "type": "ineq",
                                    "fun": volatility_constraint,
                                    "jac": volatility_jac,
                                },
                            ],
                            options={
                                "maxiter": config.max_iterations,
                                "ftol": 1e-9,
                                "disp": False,
                            },
                        )
                        if _is_feasible_candidate(
                            nonlinear_retry,
                            bounds,
                            linear,
                            volatility_constraint,
                            config.tolerance,
                        ):
                            result = nonlinear_retry
                            independently_feasible = True
            if not result.success and not independently_feasible:
                hold_seed = OptimizeResult(
                    x=np.r_[previous, np.abs(previous), np.zeros(n)],
                    success=False,
                    status=-2,
                    message="independently verified fail-closed no-trade fallback",
                )
                if _is_feasible_candidate(
                    hold_seed, bounds, linear, volatility_constraint, config.tolerance
                ):
                    result = hold_seed
                    independently_feasible = True
            # Abrupt per-name cap reductions can leave SLSQP at a singular corner near the
            # drifted holdings even though cash is feasible. Retry from exact cash only when
            # that point independently satisfies every linear, capacity and volatility bound.
            if not result.success and not independently_feasible:
                cash_initial = np.r_[np.zeros(2 * n), np.abs(previous)]
                cash_seed = OptimizeResult(
                    x=cash_initial,
                    success=False,
                    status=-1,
                    message="independently verified fail-closed cash fallback",
                )
                if _is_feasible_candidate(
                    cash_seed, bounds, linear, volatility_constraint, config.tolerance
                ):
                    result = minimize(
                        objective, cash_initial, jac=objective_jac, method="SLSQP",
                        bounds=bounds,
                        constraints=[linear, {"type": "ineq", "fun": volatility_constraint,
                                              "jac": volatility_jac}],
                        options={"maxiter": config.max_iterations, "ftol": 1e-9,
                                 "disp": False},
                    )
                    independently_feasible = _is_feasible_candidate(
                        result, bounds, linear, volatility_constraint, config.tolerance
                    )
                    if not result.success and not independently_feasible:
                        # SLSQP can reject the exact feasible corner on some SciPy builds.
                        # Holding cash is safer than converting that numerical result into an
                        # invalid strategy path, and the rebalance records non-convergence.
                        result = cash_seed
                        independently_feasible = True
            if not result.success and not independently_feasible:
                # A numerical failure on an otherwise ordinary rebalance can make the
                # configured turnover cap the only constraint preventing the deterministic
                # cash fallback. In that exceptional case, permit a fully costed liquidation
                # while retaining the name, gross, net, factor, sleeve, capacity and
                # volatility constraints. This is fail-closed: it cannot create exposure.
                emergency_upper = linear_upper.copy()
                emergency_turnover = max(turnover_limit, float(np.abs(previous).sum()))
                emergency_upper[turnover_row] = emergency_turnover
                emergency_linear = LinearConstraint(
                    linear_matrix, -np.inf, emergency_upper
                )
                emergency_cash = OptimizeResult(
                    x=np.r_[np.zeros(2 * n), np.abs(previous)],
                    success=False,
                    status=-3,
                    message="independently verified emergency cash liquidation",
                )
                if _is_feasible_candidate(
                    emergency_cash,
                    bounds,
                    emergency_linear,
                    volatility_constraint,
                    config.tolerance,
                ):
                    result = emergency_cash
                    linear = emergency_linear
                    turnover_limit = emergency_turnover
                    independently_feasible = True
            if (
                not result.success
                and not independently_feasible
                and config.liquidity_limited_cap_reduction
            ):
                # If jointly tightened risk budgets are linearly infeasible under the ADV
                # bounds, execute the maximum per-name liquidation that is actually tradable.
                # Remaining risk-budget breaches are measured on the accepted target and fail
                # the operational gate. This preserves an executable path without inventing
                # liquidity or silently accepting an optimizer candidate.
                liquidation_weight = np.sign(previous) * np.maximum(
                    np.abs(previous) - capacity, 0.0
                )
                result = OptimizeResult(
                    x=np.r_[
                        liquidation_weight,
                        np.abs(liquidation_weight),
                        np.abs(liquidation_weight - previous),
                    ],
                    success=False,
                    status=-5,
                    message="maximum ADV-constrained emergency liquidation",
                )
                independently_feasible = True
                emergency_constraint_override = True
            if not result.success and not independently_feasible:
                return CrossAssetResult(pd.DataFrame(records).set_index("session"), pd.DataFrame(weights),
                                        pd.DataFrame(rebalances), "INVALID",
                                        f"RISK_BUDGET_OPTIMIZER_FAILED_{result.status}_"
                                        f"{result.message}_LINEAR_{linear_fallback_reason}")
            target = active.copy()
            target.loc[names] = result.x[:n]
            trade = target - active
            daily_vol = pd.Series(0.0, index=columns)
            daily_vol.loc[names] = np.sqrt(np.maximum(np.diag(covariance), 0))
            projected = estimate_costs(active.to_numpy(), target.to_numpy(), daily_vol.to_numpy(),
                                       adv.loc[session].fillna(0).to_numpy(), config.nav, costs)
            pending_cost = projected["transaction"]
            pending_turnover = float(trade.abs().sum())
            active = target
            factor_exposure = factor_loadings.T @ target
            sleeve_gross = target.abs().groupby(asset_sleeves).sum()
            long_gross = float(target.clip(lower=0).sum())
            short_gross = float(target.clip(upper=0).abs().sum())
            name_cap_excess = float(
                np.maximum(np.abs(target.loc[names].to_numpy()) - scaled_name, 0).max()
            )
            short_budget_ratio = (
                short_gross / float(scaled_short_cap)
                if scaled_short_cap not in (None, 0)
                else (0.0 if short_gross == 0 else np.nan)
            )
            long_budget_ratio = (
                long_gross / float(scaled_long_cap)
                if scaled_long_cap not in (None, 0)
                else (0.0 if long_gross == 0 else np.nan)
            )
            rebalances.append({"session": session, "eligible_assets": len(names),
                               "gross": float(target.abs().sum()), "net": float(target.sum()),
                               "long_gross": long_gross,
                               "long_gross_cap": scaled_long_cap,
                               "long_gross_budget_ratio": long_budget_ratio,
                               "short_gross": short_gross,
                               "short_gross_cap": scaled_short_cap,
                               "short_gross_budget_ratio": short_budget_ratio,
                               "maximum_name_cap_excess": name_cap_excess,
                               "turnover": pending_turnover,
                               "turnover_limit": turnover_limit,
                               "forecast_volatility": float(
                                   np.sqrt(result.x[:n] @ covariance @ result.x[:n] * 252)
                               ),
                               "optimizer_converged": bool(result.success),
                               "optimizer_status": int(result.status),
                               "emergency_constraint_override": emergency_constraint_override,
                               "risk_scaler": scale,
                               "long_gross_scaler": long_scale,
                               "short_gross_scaler": short_scale,
                               "net_budget_ratio": float(abs(target.sum()) / (config.net_cap * scale)),
                               "maximum_factor_budget_ratio": float(
                                   (factor_exposure.abs() / (factor_caps * scale)).max()
                               ),
                               "maximum_sleeve_budget_ratio": float(
                                   (sleeve_gross / desired_sleeve_caps).max()
                               ),
                               "maximum_sleeve_cap_excess": float(
                                   (sleeve_gross - desired_sleeve_caps).clip(lower=0).max()
                               ),
                               **{f"exposure_{key}": float(value) for key, value in factor_exposure.items()}})
        last_session = session
    return CrossAssetResult(pd.DataFrame(records).set_index("session"), pd.DataFrame(weights),
                            pd.DataFrame(rebalances).set_index("session"), "COMPLETED", "OK")
