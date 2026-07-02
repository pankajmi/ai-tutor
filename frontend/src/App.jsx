import { useState, lazy, Suspense } from "react";
import Dashboard from "./Dashboard";
import ChildProfile from "./ChildProfile";

const VoiceSessionShell = lazy(() => import("./VoiceSessionShell"));

const STORAGE_KEY = "nova_child_profile";

function loadProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveProfile(profile) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
  } catch {
    // localStorage unavailable — proceed without persisting
  }
}

export default function App() {
  const [profile, setProfile] = useState(loadProfile);

  function handleProfileCreated(data) {
    saveProfile(data);
    setProfile(data);
  }

  const path = window.location.pathname.replace(/\/$/, "") || "/";

  if (path === "/dashboard" || path.startsWith("/dashboard")) {
    return <Dashboard />;
  }

  const childId =
    new URLSearchParams(window.location.search).get("child_id") ||
    profile?.childId;

  if (path === "/conversation" || profile) {
    if (childId) {
      if (!profile) {
        saveProfile({ childId });
      }
      if (path !== "/conversation") {
        window.history.replaceState(null, "", `/conversation?child_id=${childId}`);
      }
      return (
        <Suspense
          fallback={
            <div className="w-full h-full bg-[#1a1a2e] flex items-center justify-center text-gray-400">
              Loading...
            </div>
          }
        >
          <VoiceSessionShell childId={childId} />
        </Suspense>
      );
    }
    return <ChildProfile onComplete={handleProfileCreated} />;
  }

  return <ChildProfile onComplete={handleProfileCreated} />;
}
