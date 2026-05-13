#!/usr/bin/env python3
"""Integration tests for the Flask API."""

import pytest


VALID_PAYLOAD = {
    "vpc_cidr": "10.0.0.0/16",
    "availability_zones": 2,
    "node_count": 10,
    "pods_per_node": 110,
    "eks_version": 1.28,
}


class TestCalculateEndpoint:
    def test_valid_payload_returns_200(self, client):
        response = client.post("/api/calculate", json=VALID_PAYLOAD)
        assert response.status_code == 200
        data = response.get_json()
        assert "subnets" in data

    def test_eol_eks_version_returns_400(self, client):
        payload = {**VALID_PAYLOAD, "eks_version": 1.27}
        response = client.post("/api/calculate", json=payload)
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_vpc_too_small_returns_400(self, client):
        payload = {**VALID_PAYLOAD, "vpc_cidr": "10.0.0.0/29"}
        response = client.post("/api/calculate", json=payload)
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_zero_nodes_returns_400(self, client):
        payload = {**VALID_PAYLOAD, "node_count": 0}
        response = client.post("/api/calculate", json=payload)
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_overlapping_pod_cidr_returns_400(self, client):
        payload = {**VALID_PAYLOAD, "pod_cidr": "10.0.0.0/16"}
        response = client.post("/api/calculate", json=payload)
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestValidateEndpoint:
    def test_valid_payload_returns_valid(self, client):
        response = client.post("/api/validate", json=VALID_PAYLOAD)
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is True
        assert data["error"] is None

    def test_invalid_vpc_returns_invalid(self, client):
        payload = {**VALID_PAYLOAD, "vpc_cidr": "10.0.0.0/29"}
        response = client.post("/api/validate", json=payload)
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False
        assert data["error"] is not None
