#!/usr/bin/env python3
"""Unit tests for validators module."""

import pytest
from validators import (
    is_valid_cidr,
    is_valid_vpc_cidr,
    is_valid_az_count,
    is_valid_node_count,
    is_valid_pods_per_node,
    is_valid_pod_cidr,
    is_valid_eks_version,
    validate_cluster_config,
)


class TestIsValidCidr:
    def test_valid_cidr(self):
        is_valid, error = is_valid_cidr("10.0.0.0/16")
        assert is_valid is True
        assert error is None

    def test_invalid_format(self):
        is_valid, error = is_valid_cidr("invalid")
        assert is_valid is False
        assert error is not None

    def test_empty_string(self):
        is_valid, error = is_valid_cidr("")
        assert is_valid is False
        assert error is not None

    def test_invalid_octet(self):
        is_valid, error = is_valid_cidr("10.0.0.256/16")
        assert is_valid is False

    def test_invalid_prefix(self):
        is_valid, error = is_valid_cidr("10.0.0.0/33")
        assert is_valid is False


class TestIsValidVpcCidr:
    def test_valid_vpc(self):
        is_valid, error = is_valid_vpc_cidr("10.0.0.0/16")
        assert is_valid is True

    def test_too_large(self):
        is_valid, error = is_valid_vpc_cidr("10.0.0.0/29")
        assert is_valid is False
        assert "smaller" in error.lower()

    def test_valid_large(self):
        is_valid, error = is_valid_vpc_cidr("10.0.0.0/15")
        assert is_valid is True

    def test_valid_small(self):
        is_valid, error = is_valid_vpc_cidr("10.0.0.0/24")
        assert is_valid is True


class TestIsValidAzCount:
    def test_valid_counts(self):
        for count in [1, 2, 3, 4, 5, 6]:
            is_valid, error = is_valid_az_count(count)
            assert is_valid is True

    def test_zero_az(self):
        is_valid, error = is_valid_az_count(0)
        assert is_valid is False

    def test_too_many_az(self):
        is_valid, error = is_valid_az_count(7)
        assert is_valid is False


class TestIsValidNodeCount:
    def test_valid_count(self):
        is_valid, error = is_valid_node_count(10)
        assert is_valid is True

    def test_zero_nodes(self):
        is_valid, error = is_valid_node_count(0)
        assert is_valid is False

    def test_too_many_nodes(self):
        is_valid, error = is_valid_node_count(10001)
        assert is_valid is False


class TestIsValidPodsPerNode:
    def test_valid_count(self):
        is_valid, error = is_valid_pods_per_node(110)
        assert is_valid is True

    def test_zero_pods(self):
        is_valid, error = is_valid_pods_per_node(0)
        assert is_valid is False

    def test_too_many_pods(self):
        is_valid, error = is_valid_pods_per_node(1001)
        assert is_valid is False


class TestIsValidPodCidr:
    def test_none_is_valid(self):
        is_valid, error = is_valid_pod_cidr(None)
        assert is_valid is True
        assert error is None

    def test_empty_is_valid(self):
        is_valid, error = is_valid_pod_cidr("")
        assert is_valid is True

    def test_valid_cidr(self):
        is_valid, error = is_valid_pod_cidr("100.64.0.0/10")
        assert is_valid is True

    def test_invalid_format(self):
        is_valid, error = is_valid_pod_cidr("invalid")
        assert is_valid is False

    def test_no_overlap(self):
        is_valid, error = is_valid_pod_cidr("100.64.0.0/10", "10.0.0.0/16")
        assert is_valid is True

    def test_overlaps_vpc(self):
        is_valid, error = is_valid_pod_cidr("10.0.0.0/16", "10.0.0.0/16")
        assert is_valid is False
        assert "overlaps" in error.lower()


class TestIsValidEksVersion:
    def test_valid_versions(self):
        for version in [1.25, 1.26, 1.27, 1.28, 1.29]:
            is_valid, error = is_valid_eks_version(version)
            assert is_valid is True

    def test_invalid_version(self):
        is_valid, error = is_valid_eks_version(1.24)
        assert is_valid is False


class TestValidateClusterConfig:
    def test_valid_config(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 10, 110, 1.27)
        assert is_valid is True

    def test_invalid_vpc(self):
        is_valid, error = validate_cluster_config("10.0.0.0/29", 2, 10, 110, 1.27)
        assert is_valid is False

    def test_invalid_az(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 0, 10, 110, 1.27)
        assert is_valid is False

    def test_invalid_nodes(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 0, 110, 1.27)
        assert is_valid is False

    def test_invalid_pods(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 10, 0, 1.27)
        assert is_valid is False

    def test_invalid_pod_cidr(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="10.0.0.0/16")
        assert is_valid is False

    def test_valid_custom_pod_cidr(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 10, 110, 1.27, pod_cidr="100.64.0.0/10")
        assert is_valid is True

    def test_invalid_eks(self):
        is_valid, error = validate_cluster_config("10.0.0.0/16", 2, 10, 110, 1.24)
        assert is_valid is False