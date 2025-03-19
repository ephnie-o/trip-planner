from django.db import models

# Create your models here.
class Trip(models.Model):
    current_location = models.CharField(max_length=255)
    current_location_address = models.CharField(max_length=255, blank=True, null=True)
    pickup_location = models.CharField(max_length=255)
    pickup_address = models.CharField(max_length=255, blank=True, null=True)
    dropoff_location = models.CharField(max_length=255)
    dropoff_address = models.CharField(max_length=255, blank=True, null=True)
    current_cycle_used = models.FloatField()

    total_distance_miles = models.FloatField(null=True, blank=True)
    route_geometry = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trip from {self.pickup_location} to {self.dropoff_location}"

class Stop(models.Model):

    STOP_TYPES = (
        ('Fuel', 'Fuel Stop'),
        ('Pickup', 'Pickup'),
        ('Dropoff', 'Dropoff'),
    )
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='stops')
    type = models.CharField(max_length=10, choices=STOP_TYPES)
    location_lat = models.FloatField()
    location_lon = models.FloatField()
    duration_minutes = models.IntegerField()

    def __str__(self):
        return f"{self.type} at ({self.location_lat}, {self.location_lon})"

class TripStatus(models.Model):
    STATUS_CHOICES = [
        ('OFF_DUTY', 'Off Duty'),
        ('SLEEPER', 'Sleeper Berth'),
        ('DRIVING', 'Driving'),
        ('ON_DUTY', 'On Duty (Not Driving)')
    ]

    trip = models.ForeignKey('Trip', on_delete=models.CASCADE, related_name='statuses')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.status} at {self.timestamp} in {self.location}"

