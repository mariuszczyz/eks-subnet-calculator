#!/usr/bin/env python3
"""Unit tests for subnet_calculator module."""

import pytest
from subnet_calculator import (
    parse_cidr,
    calculate_subnet_size,
    calculate_control_plane_size,
    calculate_subnets,
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


class TestCalculateControlPlaneSize:
    def test_minimum_size(self):
        prefix = calculate_control_plane_size()
        assert prefix == 28



class TestCalculateSubnets:
    def test_basic_calculation(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27)
        assert result["vpc_cidr"] == "10.0.0.0/16"
        assert result["availability_zones"] == 2
        assert result["pods_per_node"] == 110
        assert len(result["subnets"]) == 8

    def test_three_azs(self):
        result = calculate_subnets("10.0.0.0/12", 3, 10, 110, 1.27)
        assert result["availability_zones"] == 3
        assert len(result["subnets"]) == 11

    def test_insufficient_space(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/28", 2, 10, 110, 1.27)

    def test_validation_results(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 110, 1.27)
        assert "validation" in result
        assert len(result["validation"]) > 0
        for v in result["validation"]:
            assert v["passed"] is True

    def test_summary(self):
        result = calculate_subnets("10.0.0.0/12", 2, 10, 110, 1.27)
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
        result = calculate_subnets("10.0.0.0/16", 1, 10, 110, 1.27)
        assert result["availability_zones"] == 1
        assert len(result["subnets"]) == 5

    def test_max_azs(self):
        result = calculate_subnets("10.0.0.0/12", 6, 10, 110, 1.27)
        assert result["availability_zones"] == 6
        assert len(result["subnets"]) == 20

    def test_large_vpc(self):
        result = calculate_subnets("10.0.0.0/12", 3, 100, 110, 1.29)
        assert result["vpc_cidr"] == "10.0.0.0/12"


class TestCustomPodCidr:
    def test_custom_pod_cidr_success(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="100.64.0.0/10")
        pod_subnet = next(s for s in result["subnets"] if s["purpose"] == "pod")
        assert pod_subnet["cidr"] == "100.64.0.0/10"
        assert pod_subnet["custom"] is True

    def test_custom_pod_cidr_not_in_vpc(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="100.64.0.0/10")
        # Pod CIDR should not consume VPC space (custom pod CIDR is external)
        assert result["summary"]["vpc_utilization_percent"] < 50

    def test_custom_pod_cidr_too_small(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/16", 2, 1000, 110, 1.27, pod_cidr="10.200.0.0/16")

    def test_custom_pod_cidr_overlaps_vpc(self):
        with pytest.raises(ValueError):
            calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="10.0.0.0/16")

    def test_auto_pod_cidr_without_custom(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27)
        pod_subnet = next(s for s in result["subnets"] if s["purpose"] == "pod")
        assert pod_subnet["custom"] is False

    def test_custom_pod_cidr_in_response(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="100.64.0.0/10")
        assert result["pod_cidr"] == "100.64.0.0/10"

    def test_auto_pod_cidr_in_response(self):
        result = calculate_subnets("10.0.0.0/16", 2, 10, 110, 1.27)
        assert result["pod_cidr"] is None