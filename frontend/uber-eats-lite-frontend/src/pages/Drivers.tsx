import { useEffect, useState } from "react";
import api from "../api/api";

interface Driver {
  id: string;
  name: string;
  status: string;
}

export default function Drivers() {
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Driver[]>("/drivers/drivers")
      .then(res => setDrivers(res.data))
      .catch(err => setError(err.message));
  }, []);

  return (
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">🚗 Drivers</h1>
      {error && <p className="text-red-500 mt-4">Error: {error}</p>}
      <div className="mt-6 space-y-2">
        {drivers.length ? drivers.map(driver => (
          <div key={driver.id} className="border rounded-lg p-3 mx-auto w-1/2">
            <p>{driver.name}</p>
            <p className="text-gray-500">{driver.status}</p>
          </div>
        )) : <p>No drivers found</p>}
      </div>
    </div>
  );
}

