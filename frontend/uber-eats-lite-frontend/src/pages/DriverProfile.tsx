import { useEffect, useState } from "react";
import api from "../api/api";

interface DriverProfile {
  id: string;
  name: string;
  vehicle: string;
  license_number: string;
  status: string;
}

export default function DriverProfile() {
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const res = await api.get("/drivers/me");
        setProfile(res.data);
      } catch (err: any) {
        setError(err.response?.data?.detail || "Failed to load profile");
      } finally {
        setLoading(false);
      }
    };

    fetchProfile();
  }, []);

  if (loading) return <p>Loading profile...</p>;
  if (error) return <p style={{ color: "red" }}>Error: {error}</p>;
  if (!profile) return <p>No profile found</p>;

  return (
    <div>
      <h1>🚚 Driver Profile</h1>

      <p>Name: {profile.name}</p>
      <p>Vehicle: {profile.vehicle}</p>
      <p>License Number: {profile.license_number}</p>
      <p>Status: {profile.status}</p>
    </div>
  );
}
