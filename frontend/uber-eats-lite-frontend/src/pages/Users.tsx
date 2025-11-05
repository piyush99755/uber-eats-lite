import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";

interface User {
  id: string;
  name: string;
  email: string;
}

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ name: "", email: "" });

  const fetchUsers = async () => {
    try {
      const res = await api.get<User[]>("/users/users");
      setUsers([...res.data].reverse());
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleCreateUser = async () => {
    if (!form.name || !form.email) {
      alert("Please fill all fields");
      return;
    }

    setLoading(true);
    try {
      const res = await api.post<User>("/users/users", form);
      setUsers((prev) => [res.data, ...prev]);
      setShowModal(false);
      setForm({ name: "", email: "" });
    } catch (_err: unknown) {
      console.error("Delete user error:", _err);
      alert("Failed to delete user");
    }finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (id: string) => {
    if (!confirm("Delete this user?")) return;
    try {
      await api.delete(`/users/${id}`);
      setUsers((prev) => prev.filter((u) => u.id !== id));
    } catch (_err: unknown) {
      console.error("Delete user error:", _err);
      alert("Failed to delete user");
    }
  };

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">👥 Users</h1>
        <Button onClick={() => setShowModal(true)}>➕ Add User</Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {users.length ? (
          users.map((user) => (
            <div key={user.id} className="border rounded-lg p-4 bg-white shadow">
              <p className="font-semibold">{user.name}</p>
              <p className="text-gray-500 text-sm">{user.email}</p>
              <Button
                onClick={() => handleDeleteUser(user.id)}
                className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 mt-3 rounded"
              >
                🗑 Delete
              </Button>
            </div>
          ))
        ) : (
          <p>No users found</p>
        )}
      </div>

      <Modal show={showModal} onClose={() => setShowModal(false)} title="Add New User">
        <input
          type="text"
          placeholder="Full Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          className="border p-2 w-full mb-4 rounded"
        />
        <Button onClick={handleCreateUser} loading={loading} className="w-full">
          Create User
        </Button>
      </Modal>
    </div>
  );
}
