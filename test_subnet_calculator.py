#!/usr/bin/env python3
"""Unit tests for subnet_calculator module."""

import pytest
from subnet_calculator import (
    parse_cidr,
    calculate_subnet_size,
    calculate_control_plane_size,
    calculate_subnets,
    suggest_minimum_vpc_cidr,
)


class TestParseCidr:
    def test_valid_cidr(self):
        network = parse_cidr("10.0.0.0/16")
        assert str(network) == "10.0.0.0/16"

    def test_invalid_cidr(self):
        with pytest.raises(ValueError):
            parse_cidr("invalid")


class TestCalculateSubnetSize:
    def test_small_cluster_6az(self):
        # ips_per_az = 5*110/6 + 5*16/6 + 128 = 91.67 + 13.33 + 128 = 233 → /24 (256)
        prefix = calculate_subnet_size(5, 110, 6)
        assert prefix == 24

    def test_small_cluster_2az(self):
        # ips_per_az = 5*110/2 + 5*16/2 + 128 = 275 + 40 + 128 = 443 → /23 (512)
        prefix = calculate_subnet_size(5, 110, 2)
        assert prefix == 23

    def test_large_cluster_6az(self):
        # ips_per_az = 100*110/6 + 100*16/6 + 128 = 1833 + 267 + 128 = 2228 → /20 (4096)
        prefix = calculate_subnet_size(100, 110, 6)
        assert prefix == 20

    def test_very_large_cluster_6az(self):
        # ips_per_az = 10000*110/6 + 10000*16/6 + 128 = 210128 → /14 (262144)
        prefix = calculate_subnet_size(10000, 110, 6)
        assert prefix == 14

    def test_fewer_azs_require_larger_subnets(self):
        # 2 AZs: each zone handles more nodes → needs bigger subnet → smaller prefix
        prefix_2az = calculate_subnet_size(100, 110, 2)
        prefix_6az = calculate_subnet_size(100, 110, 6)
        assert prefix_2az < prefix_6az

    def test_node_count_affects_size(self):
        small = calculate_subnet_size(10, 110, 2)
        large = calculate_subnet_size(10000, 110, 2)
        assert large < small  # larger node count → smaller prefix → bigger subnet

    def test_pods_per_node_affects_size(self):
        small = calculate_subnet_size(100, 10, 2)
        large = calculate_subnet_size(100, 200, 2)
        assert large < small  # more pods → smaller prefix → bigger subnet

    def test_single_az_requires_largest_subnet(self):
        # ips_per_az = 10*110/1 + 10*16/1 + 128 = 1388 → /21 (2048)
        prefix = calculate_subnet_size(10, 110, 1)
        assert prefix == 21

    def test_zero_azs_raises(self):
        with pytest.raises(ValueError):
            calculate_subnet_size(10, 110, 0)

    def test_custom_pod_cidr_excludes_pods_from_sizing(self):
        # Without custom pod CIDR: 1000*30/3 + 1000*16/3 + 128 = 15461 → /18
        prefix_standard = calculate_subnet_size(1000, 30, 3)
        # With custom pod CIDR: 1000/3 + 128 = 461 → /23
        prefix_custom = calculate_subnet_size(1000, 30, 3, use_custom_pod_cidr=True)
        assert prefix_standard == 18
        assert prefix_custom == 23
        assert prefix_custom > prefix_standard  # smaller subnet needed


class TestCalculateControlPlaneSize:
    def test_minimum_size(self):
        prefix = calculate_control_plane_size()
        assert prefix == 28



class TestCalculateSubnets:
    def test_basic_calculation(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28)
        assert result["vpc_cidr"] == "10.0.0.0/16"
        assert result["availability_zones"] == 2
        assert result["pods_per_node"] == 110
        assert len(result["subnets"]) == 8

    def test_three_azs(self):
        result = calculate_subnets("10.0.0.0/12", 3, 10, 110, 1.28)
        assert result["availability_zones"] == 3
        assert len(result["subnets"]) == 11

    def test_insufficient_space(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/28", 2, 10, 110, 1.28)

    def test_validation_results(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 110, 1.28)
        assert "validation" in result
        assert len(result["validation"]) > 0
        for v in result["validation"]:
            assert v["passed"] is True

    def test_summary(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 110, 1.28)
        assert "summary" in result
        assert result["summary"]["total_subnets"] == 8
        assert "total_ips" in result["summary"]
        assert "available_ips" in result["summary"]
        assert "vpc_used" in result["summary"]
        assert "vpc_total" in result["summary"]
        assert "vpc_utilization_percent" in result["summary"]
        # VPC /12 = 1,048,576 IPs; subnets should use a fraction of that
        assert result["summary"]["vpc_used"] < result["summary"]["vpc_total"]
        assert 0 < result["summary"]["vpc_utilization_percent"] < 100


class TestEdgeCases:
    def test_single_az(self):
        result = calculate_subnets("10.0.0.0/16", 1, 10, 110, 1.28)
        assert result["availability_zones"] == 1
        assert len(result["subnets"]) == 5

    def test_max_azs(self):
        result = calculate_subnets("10.0.0.0/12", 6, 10, 110, 1.28)
        assert result["availability_zones"] == 6
        assert len(result["subnets"]) == 20

    def test_large_vpc(self):
        result = calculate_subnets("10.0.0.0/12", 3, 100, 110, 1.29)
        assert result["vpc_cidr"] == "10.0.0.0/12"


class TestSubnetDistributionFields:
    def _get_node_subnets(self, result):
        return [s for s in result["subnets"]
                if s["purpose"] in ("public", "private") and "control-plane" not in s["name"]]

    def test_actual_fields_present_on_public_and_private(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        for s in self._get_node_subnets(result):
            assert "actual_nodes" in s, f"Missing actual_nodes on {s['name']}"
            assert "actual_pods"  in s, f"Missing actual_pods on {s['name']}"
            assert "max_nodes"    in s, f"Missing max_nodes on {s['name']}"
            assert "max_pods"     in s, f"Missing max_pods on {s['name']}"

    def test_actual_nodes_sum_equals_node_count(self):
        result = calculate_subnets("10.0.0.0/12", 3, 10, 30, 1.28)
        private = [s for s in result["subnets"] if s["purpose"] == "private"
                   and "control-plane" not in s["name"]]
        assert sum(s["actual_nodes"] for s in private) == 10

    def test_actual_nodes_even_distribution(self):
        result = calculate_subnets("10.0.0.0/12", 3, 9, 30, 1.28)
        private = [s for s in result["subnets"] if s["purpose"] == "private"
                   and "control-plane" not in s["name"]]
        assert all(s["actual_nodes"] == 3 for s in private)

    def test_actual_nodes_uneven_distribution(self):
        # 10 nodes / 3 AZs → [4, 3, 3]
        result = calculate_subnets("10.0.0.0/12", 3, 10, 30, 1.28)
        private = [s for s in result["subnets"] if s["purpose"] == "private"
                   and "control-plane" not in s["name"]]
        counts = [s["actual_nodes"] for s in private]
        assert counts == [4, 3, 3]

    def test_actual_pods_equals_actual_nodes_times_pods_per_node(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        for s in self._get_node_subnets(result):
            assert s["actual_pods"] == s["actual_nodes"] * 30

    def test_max_nodes_positive_and_exceeds_actual(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        for s in self._get_node_subnets(result):
            assert s["max_nodes"] > 0
            assert s["max_nodes"] >= s["actual_nodes"]

    def test_max_pods_equals_max_nodes_times_pods_per_node(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        for s in self._get_node_subnets(result):
            assert s["max_pods"] == s["max_nodes"] * 30

    def test_max_nodes_formula_without_custom_pod_cidr(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        s = next(s for s in result["subnets"] if s["name"] == "az1-private")
        expected = max(0, (s["available_ips"] - 128) // (30 + 16))
        assert s["max_nodes"] == expected

    def test_max_nodes_formula_with_custom_pod_cidr(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28, pod_cidr="100.64.0.0/10")
        s = next(s for s in result["subnets"] if s["name"] == "az1-private")
        expected = max(0, s["available_ips"] - 128)
        assert s["max_nodes"] == expected

    def test_public_and_private_same_az_have_same_actual_nodes(self):
        result = calculate_subnets("10.0.0.0/12", 3, 10, 30, 1.28)
        for az in range(1, 4):
            pub  = next(s for s in result["subnets"] if s["name"] == f"az{az}-public")
            priv = next(s for s in result["subnets"] if s["name"] == f"az{az}-private")
            assert pub["actual_nodes"] == priv["actual_nodes"]
            assert pub["max_nodes"]    == priv["max_nodes"]

    def test_control_plane_subnet_has_no_distribution_fields(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 30, 1.28)
        cp = next(s for s in result["subnets"] if "control-plane" in s["name"])
        assert "actual_nodes" not in cp
        assert "max_nodes"    not in cp


class TestSuggestMinimumVpcCidr:
    def test_suggestion_included_in_overflow_error(self):
        # 1000 nodes × 30 pods, 3 AZs, /16 VPC — overflows without custom pod CIDR
        with pytest.raises(ValueError, match=r"Consider using a /\d+ VPC CIDR"):
            calculate_subnets("10.0.0.0/16", 3, 1000, 30, 1.28)

    def test_suggestion_is_valid_prefix(self):
        suggestion = suggest_minimum_vpc_cidr(1000, 30, 3)
        assert suggestion.startswith("/")
        prefix = int(suggestion[1:])
        assert 8 <= prefix <= 28

    def test_suggestion_fits_the_cluster(self):
        # The suggested VPC must actually be large enough to run calculate_subnets without error
        suggestion = suggest_minimum_vpc_cidr(1000, 30, 3)
        prefix = int(suggestion[1:])
        result = calculate_subnets(f"10.0.0.0{suggestion}", 3, 1000, 30, 1.28)
        assert result["summary"]["vpc_used"] <= result["summary"]["vpc_total"]

    def test_suggestion_with_custom_pod_cidr(self):
        # With custom pod CIDR the node subnets are smaller, suggestion should be smaller prefix
        prefix_standard = int(suggest_minimum_vpc_cidr(1000, 30, 3)[1:])
        prefix_custom = int(suggest_minimum_vpc_cidr(1000, 30, 3, use_custom_pod_cidr=True)[1:])
        assert prefix_custom > prefix_standard  # larger number = smaller block needed


class TestCustomPodCidr:
    def test_custom_pod_cidr_success(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28, pod_cidr="100.64.0.0/10")
        pod_subnet = next(s for s in result["subnets"] if s["purpose"] == "pod")
        assert pod_subnet["cidr"] == "100.64.0.0/10"
        assert pod_subnet["custom"] is True

    def test_custom_pod_cidr_not_in_vpc(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28, pod_cidr="100.64.0.0/10")
        # Pod CIDR should not consume VPC space (custom pod CIDR is external)
        assert result["summary"]["vpc_utilization_percent"] < 50

    def test_custom_pod_cidr_too_small(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/16", 2, 1000, 110, 1.28, pod_cidr="10.200.0.0/16")

    def test_custom_pod_cidr_overlaps_vpc(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28, pod_cidr="10.0.0.0/16")

    def test_auto_pod_cidr_without_custom(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28)
        pod_subnet = next(s for s in result["subnets"] if s["purpose"] == "pod")
        assert pod_subnet["custom"] is False

    def test_custom_pod_cidr_in_response(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28, pod_cidr="100.64.0.0/10")
        assert result["pod_cidr"] == "100.64.0.0/10"

    def test_auto_pod_cidr_in_response(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.28)
        assert result["pod_cidr"] is None

    def test_custom_pod_cidr_large_cluster_fits_in_16_vpc(self):
        # Regression: 1000 nodes × 30 pods, 3 AZs, /16 VPC with custom pod CIDR
        # previously overflowed because pod IPs were counted in node subnet size
        result = calculate_subnets("10.0.0.0/16", 3, 1000, 30, 1.28, pod_cidr="100.64.0.0/16")
        assert result["summary"]["vpc_used"] <= result["summary"]["vpc_total"]
        node_subnets = [s for s in result["subnets"] if "control-plane" not in s["name"]
                        and s["purpose"] in ("public", "private")]
        for s in node_subnets:
            assert s["cidr"].endswith("/23"), f"Expected /23 node subnet, got {s['cidr']}"