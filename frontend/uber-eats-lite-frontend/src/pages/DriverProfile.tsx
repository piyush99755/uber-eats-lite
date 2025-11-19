import { useEffect, useState } from "react";
import api from "../api/api";
import { toast, ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

export default function DriverProfile() {
  const [driver, setDriver] = useState<any>(null);
  const [vehicle, setVehicle] = useState("");

  // Use token from localStorage
  const token = localStorage.getItem("token");
  const API_BASE = "/drivers";
  // Fetch driver profile on mount
  useEffect(() => {
    if (!token) return;

    api
      .get("/drivers/me") // no need to manually set headers; api.ts interceptor handles it
      .then((res) => {
        setDriver(res.data);
        setVehicle(res.data.vehicle || "");
      })
      .catch((err) => {
        console.error("Failed to fetch driver profile:", err);
        toast.error("Failed to fetch driver profile");
      });
  }, [token]);

  // Update vehicle
  const updateVehicle = async () => {
  try {
    const res = await api.put(`${API_BASE}/update-vehicle`, { vehicle });
    if (res.data.success) {
      toast.success(res.data.message);
      setDriver((prev: any) => ({ ...prev, vehicle }));
    } else {
      toast.error(res.data.message);
    }
  } catch (err) {
    console.error("Failed to update vehicle:", err);
    toast.error("Failed to update vehicle");
  }
};

  // Delete profile
  const deleteProfile = async () => {
    if (!confirm("Are you sure? This cannot be undone.")) return;

    try {
      const res = await api.delete("/drivers/me");
      if (res.data.success) {
        toast.success(res.data.message);
        localStorage.clear();
        window.location.href = "/"; // redirect to login/home
      } else {
        toast.error(res.data.message || "Failed to delete profile");
      }
    } catch (err: any) {
      console.error("Failed to delete profile:", err);
      toast.error(err.response?.data?.message || "Failed to delete profile");
    }
  };

  if (!driver) return <p>Loading...</p>;

  return (
    <div>
      <ToastContainer position="top-right" />
      <h2 className="text-2xl font-bold mb-4">Driver Profile</h2>

      <p><strong>Name:</strong> {driver.name}</p>
      <p><strong>License Number:</strong> {driver.license_number}</p>

      <label className="block mt-4">
        <span className="font-bold">Vehicle:</span>
        <input
          value={vehicle}
          onChange={(e) => setVehicle(e.target.value)}
          className="p-2 border rounded w-full mt-1"
        />
      </label>

      <button
        onClick={updateVehicle}
        className="mt-2 bg-green-600 text-white px-4 py-2 rounded"
      >
        Update Vehicle
      </button>

      <button
        onClick={deleteProfile}
        className="mt-4 bg-red-600 text-white px-4 py-2 rounded"
      >
        Delete Profile
      </button>
    </div>
  );
}
