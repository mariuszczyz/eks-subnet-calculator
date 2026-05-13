#!/usr/bin/env python3
"""Flask app for EKS Subnet Calculator."""

from flask import Flask, jsonify, request, send_from_directory
import subnet_calculator
import validators

app = Flask(__name__, static_folder='.', static_url_path='')


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/calculate', methods=['POST'])
def calculate():
    try:
        data = subnet_calculator.calculate_subnets(
            vpc_cidr=request.json.get('vpc_cidr'),
            availability_zones=request.json.get('availability_zones', 2),
            node_count=request.json.get('node_count', 10),
            pods_per_node=request.json.get('pods_per_node', 110),
            eks_version=request.json.get('eks_version', 1.27),
            pod_cidr=request.json.get('pod_cidr')
        )
        return jsonify(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/validate', methods=['POST'])
def validate():
    try:
        is_valid, error = validators.validate_cluster_config(
            vpc_cidr=request.json.get('vpc_cidr'),
            az_count=request.json.get('availability_zones', 2),
            node_count=request.json.get('node_count', 10),
            pods_per_node=request.json.get('pods_per_node', 110),
            eks_version=request.json.get('eks_version', 1.27),
            pod_cidr=request.json.get('pod_cidr')
        )
        return jsonify({'valid': is_valid, 'error': error})
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5555)