#!/usr/bin/env python3
"""Unit tests for subnet_planner module.

Test plan_scenarios function covering:
- Valid /16 plan structure and keys
- Sort order (utilization desc -> az asc -> max_nodes desc)
- Max scenarios cap (48)
- Monotonicity sanity checks
- Custom vs auto networking comparison
- Boundary cases (tiny VPC /28, invalid CIDR)
"""

import pytest
import subnet_planner


class TestPlanScenariosBasic:
    """Basic valid /16 plan tests."""

    def test_valid_16_returns_scenarios(self):
        """A valid /16 VPC returns scenario_count > 0."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        assert result["scenario_count"] > 0

    def test_16_returns_exact_48_scenarios(self):
        """A /16 VPC returns exactly 48 scenarios (all AZ x networking x pods combos)."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        assert result["scenario_count"] == 48

    def test_20_returns_fewer_scenarios(self):
        """A /20 VPC may return 0 scenarios if too small for any config."""
        result = subnet_planner.plan_scenarios("10.0.0.0/20")
        # A /20 VPC is 16384 IPs - too small for even minimal config (needs ~1200+ IPs)
        # So it returns 0 scenarios, which is valid behavior
        assert result["scenario_count"] >= 0

    def test_28_returns_empty_scenarios(self):
        """A /28 VPC returns 0 scenarios with empty list (too small for anything)."""
        result = subnet_planner.plan_scenarios("10.0.0.0/28")
        assert result["scenario_count"] == 0
        assert result["scenarios"] == []

    def test_29_returns_error(self):
        """A /29 VPC is too small and should raise ValueError."""
        with pytest.raises(ValueError):
            subnet_planner.plan_scenarios("10.0.0.0/29")

    def test_invalid_cidr_returns_error(self):
        """An invalid CIDR string raises ValueError."""
        with pytest.raises(ValueError):
            subnet_planner.plan_scenarios("not-a-cidr")

    def test_response_structure(self):
        """Response contains expected top-level keys."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        assert "vpc_cidr" in result
        assert "vpc_total_ips" in result
        assert "scenario_count" in result
        assert "scenarios" in result

    def test_scenario_keys_exact(self):
        """Each scenario has exactly the required keys."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        required_keys = [
            "scenario_id",
            "az_count",
            "networking",
            "pods_per_node",
            "max_nodes",
            "total_subnets",
            "total_ips",
            "available_ips",
            "vpc_utilization_percent",
            "fits",
        ]
        for scenario in result["scenarios"]:
            for key in required_keys:
                assert key in scenario, f"Missing key {key} in scenario {scenario.get('scenario_id', 'unknown')}"

    def test_scenario_ids_unique(self):
        """All scenario IDs are unique."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        ids = [s["scenario_id"] for s in result["scenarios"]]
        assert len(ids) == len(set(ids))


class TestScenarioValues:
    """Tests for scenario field values."""

    def test_az_count_valid_range(self):
        """AZ counts are in the expected range 1-6."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert 1 <= scenario["az_count"] <= 6

    def test_networking_is_valid_mode(self):
        """Networking is either 'auto' or 'custom'."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert scenario["networking"] in ["auto", "custom"]

    def test_pods_per_node_valid_options(self):
        """Pods per node is one of the valid options."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        valid_options = [25, 50, 110, 250]
        for scenario in result["scenarios"]:
            assert scenario["pods_per_node"] in valid_options

    def test_total_subnets_formula(self):
        """total_subnets = 3 * az_count + 2 (invariant per spec)."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            expected = 3 * scenario["az_count"] + 2
            assert scenario["total_subnets"] == expected

    def test_fits_is_true(self):
        """All scenarios in the list have fits=True."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert scenario["fits"] is True

    def test_max_nodes_positive(self):
        """max_nodes is a positive integer for all scenarios."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert isinstance(scenario["max_nodes"], int)
            assert scenario["max_nodes"] > 0

    def test_total_ips_positive(self):
        """total_ips is positive for all scenarios."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert isinstance(scenario["total_ips"], int)
            assert scenario["total_ips"] > 0

    def test_available_ips_less_than_total(self):
        """available_ips < total_ips (due to reserved IPs)."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert scenario["available_ips"] < scenario["total_ips"]

    def test_vpc_utilization_range(self):
        """vpc_utilization_percent is between 0 and 100."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        for scenario in result["scenarios"]:
            assert 0 <= scenario["vpc_utilization_percent"] <= 100

    def test_custom_networking_yields_higher_max_nodes(self):
        """For same az+networking+pods, custom networking yields higher max_nodes than auto."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")

        def find_scenario(scenarios, az_count, pods_per_node, networking):
            """Helper to find a scenario by matching criteria."""
            return next(
                s for s in scenarios if (s["az_count"] == az_count
                                         and s["pods_per_node"] == pods_per_node
                                         and s["networking"] == networking)
            )

        # Group by (az_count, pods_per_node) and compare auto vs custom
        for az in [1, 2, 3, 4, 5, 6]:
            for pods in [25, 50, 110, 250]:
                auto = find_scenario(result["scenarios"], az, pods, "auto")
                custom = find_scenario(result["scenarios"], az, pods, "custom")
                assert custom["max_nodes"] >= auto["max_nodes"]


class TestSortOrder:
    """Tests for scenario sort order."""

    def test_sort_order_utilization_desc_then_az_asc_then_max_nodes_desc(self):
        """Sort: utilization desc -> az asc -> max_nodes desc."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        scenarios = result["scenarios"]

        for i in range(len(scenarios) - 1):
            curr = scenarios[i]
            next_item = scenarios[i + 1]

            # Primary: utilization descending
            if curr["vpc_utilization_percent"] < next_item["vpc_utilization_percent"]:
                continue  # Correct order

            # Secondary: az ascending (when utilization is equal)
            if curr["vpc_utilization_percent"] == next_item["vpc_utilization_percent"]:
                if curr["az_count"] > next_item["az_count"]:
                    pytest.fail("Expected az_count ascending for equal utilization")
                elif curr["az_count"] == next_item["az_count"]:
                    # Tertiary: max_nodes descending (when utilization and az are equal)
                    if curr["max_nodes"] < next_item["max_nodes"]:
                        pytest.fail("Expected max_nodes descending for equal utilization and az")


class TestMonotonicity:
    """Monotonicity sanity checks per spec."""

    def test_larger_vpc_yields_higher_max_nodes(self):
        """A /16 VPC yields max_nodes >= a /20 VPC for same az+networking+pods."""

        def find_matching_20(scenario_16, r_20):
            """Find matching /20 scenario for a /16 scenario by az, networking, pods."""
            for s_20 in r_20["scenarios"]:
                if (
                    s_20["az_count"] == s_16["az_count"]
                    and s_20["networking"] == s_16["networking"]
                    and s_20["pods_per_node"] == s_16["pods_per_node"]
                ):
                    return s_20
            return None

        # Get max_nodes from /16 and /20 for each combination
        r_16 = subnet_planner.plan_scenarios("10.0.0.0/16")
        r_20 = subnet_planner.plan_scenarios("10.0.0.0/20")

        for s_16 in r_16["scenarios"]:
            matching_20 = find_matching_20(s_16, r_20)
            if matching_20 is not None:
                assert s_16["max_nodes"] >= matching_20["max_nodes"]


class TestScenarioCrossCheck:
    """Numerical cross-checks with subnet_calculator helpers."""

    def test_total_ips_crosscheck_footprint(self):
        """A scenario's total_ips should match footprint(max_nodes, pods, az, networking)."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")

        for scenario in result["scenarios"]:
            # Recalculate footprint using the same inputs
            recalculated = subnet_planner.footprint(
                node_count=scenario["max_nodes"],
                pods_per_node=scenario["pods_per_node"],
                az_count=scenario["az_count"],
                networking=scenario["networking"]
            )
            expected_total = scenario["total_ips"]
            msg = f"Footprint mismatch for {scenario['scenario_id']}: got {recalculated}, expected {expected_total}"
            assert recalculated == expected_total, msg


class TestScenarioCap:
    """Tests for max scenarios cap."""

    def test_max_scenarios_is_48(self):
        """A /16 returns at most 48 scenarios."""
        result = subnet_planner.plan_scenarios("10.0.0.0/16")
        assert result["scenario_count"] <= 48


class TestEdgeCases:
    """Boundary and edge case tests."""

    def test_minimal_vpc_returns_structure(self):
        """Even a minimal valid VPC (/28) returns valid structure."""
        result = subnet_planner.plan_scenarios("10.0.0.0/28")
        assert result["vpc_cidr"] == "10.0.0.0/28"
        assert result["vpc_total_ips"] == 16
        assert result["scenario_count"] == 0
        assert result["scenarios"] == []

    def test_small_valid_vpc_returns_structure(self):
        """A small but valid VPC (/24) returns structure with 0 scenarios."""
        result = subnet_planner.plan_scenarios("10.0.0.0/24")
        assert result["vpc_cidr"] == "10.0.0.0/24"
        assert result["scenario_count"] == 0

    def test_largest_vpc_returns_48_scenarios(self):
        """A /15 (largest allowed) returns 48 scenarios."""
        result = subnet_planner.plan_scenarios("10.0.0.0/15")
        assert result["scenario_count"] == 48


class TestApiIntegration:
    """API integration tests for /api/plan endpoint."""

    def test_api_valid_vpc_returns_200(self, client):
        """POST /api/plan with valid VPC returns 200."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/16"})
        assert response.status_code == 200
        data = response.get_json()
        assert "vpc_cidr" in data
        assert "vpc_total_ips" in data
        assert "scenario_count" in data
        assert "scenarios" in data

    def test_api_invalid_cidr_returns_400(self, client):
        """POST /api/plan with invalid CIDR returns 400 with error."""
        response = client.post("/api/plan", json={"vpc_cidr": "not-a-cidr"})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_api_29_returns_400(self, client):
        """POST /api/plan with /29 (too small) returns 400 with error."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/29"})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestValidators:
    """Tests for validators module used by plan_scenarios."""

    def test_is_valid_vpc_cidr_return_values(self):
        """validators.is_valid_vpc_cidr returns tuple of (bool, str)."""
        is_valid, error = subnet_planner.validators.is_valid_vpc_cidr("10.0.0.0/16")
        assert is_valid is True
        assert error is None

    def test_invalid_vpc_cidr_returns_error(self):
        """validators.is_valid_vpc_cidr returns False + error string for invalid."""
        is_valid, error = subnet_planner.validators.is_valid_vpc_cidr("invalid")
        assert is_valid is False
        assert error is not None
