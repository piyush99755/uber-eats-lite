import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import Sidebar from "../components/Sidebar";
import { Menu, X } from "lucide-react";

export default function AppLayout() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`fixed md:static top-0 left-0 h-full w-64 bg-gray-900 text-white z-40 transform ${
          open ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        } transition-transform duration-300 ease-in-out`}
      >
        <div className="flex items-center justify-between md:justify-center p-4 border-b border-gray-700">
          <h1 className="text-lg font-bold">UberEats Lite</h1>
          <button className="md:hidden" onClick={() => setOpen(false)}>
            <X size={20} />
          </button>
        </div>
        <Sidebar onNavigate={() => setOpen(false)} activePath={location.pathname} />
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-h-screen md:ml-64">
        {/* Top bar (mobile) */}
        <header className="md:hidden flex items-center justify-between bg-white shadow p-4">
          <h1 className="font-bold text-lg">UberEats Lite</h1>
          <button onClick={() => setOpen(!open)}>
            <Menu size={22} />
          </button>
        </header>

        <main className="flex-1 p-4 sm:p-6 md:p-8 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
