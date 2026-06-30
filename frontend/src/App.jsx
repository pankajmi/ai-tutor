import { lazy, Suspense } from "react";
import Dashboard from "./Dashboard";

const Whiteboard = lazy(() => import("./Whiteboard"));

export default function App() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";

  if (path === "/dashboard" || path.startsWith("/dashboard")) {
    return <Dashboard />;
  }

  const childId =
    new URLSearchParams(window.location.search).get("child_id") ||
    "local_child";

  return (
    <Suspense
      fallback={
        <div className="w-full h-full bg-[#1a1a2e] flex items-center justify-center text-gray-400">
          Loading...
        </div>
      }
    >
      <Whiteboard childId={childId} />
    </Suspense>
  );
}
