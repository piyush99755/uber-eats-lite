import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";

interface Driver {
  id: string;
  name: string;
  vehicle: string;
  license_number: string;
  status: string;
}

export default function Drivers() {
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ name: "", vehicle: "", license_number: "" });

  const fetchDrivers = async () => {
    try {
      const res = await api.get<Driver[]>("/drivers/drivers");
      setDrivers([...res.data].reverse());
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    }
  };

  useEffect(() => {
    fetchDrivers();
  }, []);

  const handleCreateDriver = async () => {
    if (!form.name || !form.vehicle || !form.license_number) {
      alert("Please fill all fields");
      return;
    }

    setLoading(true);
    try {
      const res = await api.post<Driver>("/drivers/drivers", form);
      setDrivers((prev) => [res.data, ...prev]);
      setShowModal(false);
      setForm({ name: "", vehicle: "", license_number: "" });
    } catch (err) {
      alert("Failed to create driver");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDriver = async (id: string) => {
    if (!confirm("Delete this driver?")) return;
    try {
      await api.delete(`/drivers/drivers/${id}`);
      setDrivers((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      console.error(err);
      alert("Failed to delete driver");
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🚗 Drivers</h1>
        <Button onClick={() => setShowModal(true)}>➕ Add Driver</Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {drivers.length ? (
          drivers.map((driver) => (
            <div key={driver.id} className="border rounded-lg p-4 bg-white shadow">
              <p className="font-semibold">{driver.name}</p>
              <p className="text-gray-500 text-sm">{driver.vehicle}</p>
              <p className="text-sm text-gray-400">
                License: {driver.license_number}
              </p>
              <p
                className={`text-sm font-medium mt-1 ${
                  driver.status === "available"
                    ? "text-green-600"
                    : "text-yellow-500"
                }`}
              >
                {driver.status}
              </p>
              <Button
                onClick={() => handleDeleteDriver(driver.id)}
                className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 mt-3 rounded"
              >
                🗑 Delete
              </Button>
            </div>
          ))
        ) : (
          <p>No drivers found</p>
        )}
      </div>

      <Modal show={showModal} onClose={() => setShowModal(false)} title="Add New Driver">
        <input
          type="text"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="text"
          placeholder="Vehicle"
          value={form.vehicle}
          onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="text"
          placeholder="License Number"
          value={form.license_number}
          onChange={(e) => setForm({ ...form, license_number: e.target.value })}
          className="border p-2 w-full mb-4 rounded"
        />
        <Button onClick={handleCreateDriver} loading={loading} className="w-full">
          Add Driver
        </Button>
      </Modal>
    </div>
  );
}
