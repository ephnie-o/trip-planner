from rest_framework import serializers
from .models import Trip, Stop, TripStatus

class StopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stop
        fields = ['id', 'type', 'location_lat', 'location_lon', 'duration_minutes']

class TripStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripStatus
        fields = ['status', 'start_time', 'end_time', 'location']

class TripSerializer(serializers.ModelSerializer):
    stops = StopSerializer(many=True, read_only=True)

    class Meta:
        model = Trip
        fields = [
            'id',
            'current_location',
            'current_location_address',
            'pickup_location',
            'pickup_address',
            'dropoff_location',
            'dropoff_address',
            'current_cycle_used',
            'total_distance_miles',
            'route_geometry',
            'stops',
            'statuses'
        ]