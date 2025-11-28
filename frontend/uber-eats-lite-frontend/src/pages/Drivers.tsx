import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ToastContainer, toast } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

interface Driver {
  id?: string;
  name?: string;
  vehicle?: string;
  license_number?: string;
  status?: string;
}

interface DriversProps {
  role: string | null;
}

export default function Drivers({ role }: DriversProps) {
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ name: "", vehicle: "", license_number: "" });
  const [editingId, setEditingId] = useState<string | null>(null);

  const fetchDrivers = async () => {
    try {
      const endpoint = role === "admin" ? "/drivers/all" : "/drivers"; // admin fetch all
      const res = await api.get<Driver[]>(endpoint);
      setDrivers([...res.data].reverse());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      toast.error("Failed to fetch drivers");
    }
  };

  useEffect(() => {
    fetchDrivers();
  }, [role]);

  const handleOpenEdit = (driver: Driver) => {
    setForm({
      name: driver.name || "",
      vehicle: driver.vehicle || "",
      license_number: driver.license_number || "",
    });
    setEditingId(driver.id || null);
    setShowModal(true);
  };

  const handleSubmit = async () => {
    if (!form.name || !form.vehicle || !form.license_number) {
      toast.error("Please fill all fields");
      return;
    }

    setLoading(true);
    try {
      if (editingId) {
        const res = await api.put<Driver>(`/drivers/${editingId}`, form);
        setDrivers((prev) =>
          prev.map((d) => (d.id === editingId ? res.data : d))
        );
        toast.success("Driver updated successfully");
      } else {
        const res = await api.post<Driver>("/drivers", form);
        setDrivers((prev) => [res.data, ...prev]);
        toast.success("Driver added successfully");
      }
      setShowModal(false);
      setForm({ name: "", vehicle: "", license_number: "" });
      setEditingId(null);
    } catch {
      toast.error(editingId ? "Failed to update driver" : "Failed to create driver");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDriver = async (id?: string) => {
    if (!id || !confirm("Delete this driver?")) return;
    try {
      await api.delete(`/drivers/${id}`);
      setDrivers((prev) => prev.filter((d) => d.id !== id));
      toast.success("Driver deleted successfully");
    } catch {
      toast.error("Failed to delete driver");
    }
  };

  return (
    <div className="p-6">
      <ToastContainer position="top-right" />
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">🚗 Drivers</h1>
        <Button onClick={() => { setEditingId(null); setForm({ name: "", vehicle: "", license_number: "" }); setShowModal(true); }}>➕ Add Driver</Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {drivers.length ? (
          drivers.map((driver, i) => (
            <div key={driver.id || driver.license_number || i} className="border rounded-lg p-4 bg-white shadow">
              <p className="font-semibold">{driver.name || "Unnamed Driver"}</p>
              <p className="text-gray-500 text-sm">{driver.vehicle || "Unknown Vehicle"}</p>
              <p className="text-sm text-gray-400">License: {driver.license_number || "N/A"}</p>
              <p className={`text-sm font-medium mt-1 ${driver.status === "available" ? "text-green-600" : "text-yellow-500"}`}>
                {driver.status || "unknown"}
              </p>
              <div className="flex gap-2 mt-3">
                <Button onClick={() => handleOpenEdit(driver)} className="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded">✏️ Edit</Button>
                <Button onClick={() => handleDeleteDriver(driver.id)} className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded">🗑 Delete</Button>
              </div>
            </div>
          ))
        ) : (
          <p>No drivers found</p>
        )}
      </div>

      <Modal show={showModal} onClose={() => setShowModal(false)} title={editingId ? "Edit Driver" : "Add New Driver"}>
        <input type="text" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="border p-2 w-full mb-3 rounded" />
        <input type="text" placeholder="Vehicle" value={form.vehicle} onChange={(e) => setForm({ ...form, vehicle: e.target.value })} className="border p-2 w-full mb-3 rounded" />
        <input type="text" placeholder="License Number" value={form.license_number} onChange={(e) => setForm({ ...form, license_number: e.target.value })} className="border p-2 w-full mb-4 rounded" />
        <Button onClick={handleSubmit} loading={loading} className="w-full">{editingId ? "Update Driver" : "Add Driver"}</Button>
      </Modal>
    </div>
  );
}
