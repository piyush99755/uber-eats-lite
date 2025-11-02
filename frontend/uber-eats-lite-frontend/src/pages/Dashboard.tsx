import { useEffect, useState } from "react";
import { LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip } from "recharts";
import HealthCard from "../components/HealthCard";

export default function Dashboard() {
  const [ordersData, setOrdersData] = useState<{ date: string; count: number }[]>([]);

  useEffect(() => {
    // TODO: Replace with real API stats endpoint
    setOrdersData([
      { date: "Mon", count: 4 },
      { date: "Tue", count: 7 },
      { date: "Wed", count: 5 },
      { date: "Thu", count: 9 },
      { date: "Fri", count: 6 },
    ]);
  }, []);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-3xl font-bold">📊 System Dashboard</h1>

      <HealthCard />

      <div className="bg-white p-4 rounded-lg shadow mt-6">
        <h2 className="font-semibold mb-4">Orders Over Time</h2>
        <LineChart width={600} height={300} data={ordersData}>
          <Line type="monotone" dataKey="count" stroke="#4CAF50" />
          <CartesianGrid stroke="#ccc" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
        </LineChart>
      </div>
    </div>
  );
}
