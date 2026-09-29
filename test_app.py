#!/usr/bin/env python3
"""Integration tests for the Flask API."""

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


class TestPlanEndpoint:
    """Integration tests for the /api/plan endpoint."""

    def test_valid_vpc_cidr_returns_200(self, client):
        """POST /api/plan with valid VPC returns 200 with scenarios."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/16"})
        assert response.status_code == 200
        data = response.get_json()
        assert "vpc_cidr" in data
        assert "vpc_total_ips" in data
        assert "scenario_count" in data
        assert "scenarios" in data
        assert len(data["scenarios"]) == 48

    def test_20_vpc_returns_fewer_scenarios(self, client):
        """POST /api/plan with smaller VPC returns 200 with empty scenarios."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/20"})
        assert response.status_code == 200
        data = response.get_json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 0

    def test_28_vpc_returns_200_empty_scenarios(self, client):
        """POST /api/plan with tiny VPC (/28) returns 200 with empty scenarios."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/28"})
        assert response.status_code == 200
        data = response.get_json()
        assert "scenarios" in data
        assert len(data["scenarios"]) == 0

    def test_invalid_cidr_returns_400(self, client):
        """POST /api/plan with invalid CIDR returns 400 with error."""
        response = client.post("/api/plan", json={"vpc_cidr": "not-a-cidr"})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_29_prefix_returns_400(self, client):
        """POST /api/plan with /29 (too small) returns 400 with error."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/29"})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_scenario_sort_order(self, client):
        """Scenarios are sorted: utilization desc → az asc → max_nodes desc."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/16"})
        assert response.status_code == 200
        data = response.get_json()
        scenarios = data["scenarios"]

        for i in range(len(scenarios) - 1):
            curr = scenarios[i]
            next_item = scenarios[i + 1]

            # Primary: utilization descending
            if curr["vpc_utilization_percent"] < next_item["vpc_utilization_percent"]:
                continue

            # Secondary: az ascending (when utilization is equal)
            if curr["vpc_utilization_percent"] == next_item["vpc_utilization_percent"]:
                assert curr["az_count"] <= next_item["az_count"]

    def test_scenario_keys_present(self, client):
        """All scenarios have the required keys."""
        response = client.post("/api/plan", json={"vpc_cidr": "10.0.0.0/16"})
        assert response.status_code == 200
        data = response.get_json()

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

        for scenario in data["scenarios"]:
            for key in required_keys:
                assert key in scenario, f"Missing {key} in scenario {scenario.get('scenario_id', 'unknown')}"
