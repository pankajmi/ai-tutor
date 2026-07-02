import { useState } from "react";

const GRADES = [3, 4, 5, 6, 7, 8, 9, 10];
const SUBJECTS = [
  { id: "math", label: "Math", emoji: "🔢" },
  { id: "science", label: "Science", emoji: "🔬" },
  { id: "english", label: "English", emoji: "📖" },
  { id: "social_studies", label: "Social Studies", emoji: "🌍" },
];

export default function ChildProfile({ onComplete }) {
  const [name, setName] = useState("");
  const [grade, setGrade] = useState(5);
  const [subject, setSubject] = useState("math");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;

    setSaving(true);
    setError(null);
    const childId = trimmed.toLowerCase().replace(/\s+/g, "_");

    try {
      const res = await fetch("/api/children", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ child_id: childId, name: trimmed, grade }),
      });
      if (!res.ok) throw new Error("Failed to create profile");
      const data = await res.json();
      onComplete({ childId: data.id, name: data.name, subject });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "#1a1a2e",
        padding: 32,
      }}
    >
      <div
        style={{
          width: 80,
          height: 80,
          borderRadius: "50%",
          background: "linear-gradient(135deg, #a78bfa, #7ddf7d)",
          boxShadow: "0 0 60px rgba(167, 139, 250, 0.3)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 36,
          marginBottom: 24,
        }}
      >
        ✦
      </div>

      <h1
        style={{
          fontSize: 26,
          fontWeight: 700,
          color: "#f0f0e8",
          margin: 0,
          letterSpacing: "-0.02em",
        }}
      >
        Welcome to Nova
      </h1>
      <p
        style={{
          fontSize: 13,
          color: "#888",
          marginTop: 8,
          marginBottom: 32,
          textAlign: "center",
          maxWidth: 320,
          lineHeight: 1.5,
        }}
      >
        Let's set up your child's profile so I can personalise the learning experience.
      </p>

      <form
        onSubmit={handleSubmit}
        style={{
          width: "100%",
          maxWidth: 360,
          display: "flex",
          flexDirection: "column",
          gap: 20,
        }}
      >
        <div>
          <label
            style={{
              display: "block",
              fontSize: 12,
              color: "#aaa",
              marginBottom: 6,
              fontWeight: 500,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            Child's Name
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Aarav"
            required
            style={{
              width: "100%",
              padding: "12px 14px",
              borderRadius: 10,
              border: "1px solid #333",
              background: "#16213e",
              color: "#f0f0e8",
              fontSize: 15,
              outline: "none",
              boxSizing: "border-box",
            }}
            onFocus={(e) => (e.target.style.borderColor = "#7c3aed")}
            onBlur={(e) => (e.target.style.borderColor = "#333")}
          />
        </div>

        <div>
          <label
            style={{
              display: "block",
              fontSize: 12,
              color: "#aaa",
              marginBottom: 6,
              fontWeight: 500,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            Grade
          </label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {GRADES.map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGrade(g)}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: grade === g ? "2px solid #7c3aed" : "1px solid #333",
                  background: grade === g ? "#2d1b69" : "#16213e",
                  color: grade === g ? "#c4b5fd" : "#888",
                  fontSize: 14,
                  fontWeight: grade === g ? 600 : 400,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                Class {g}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label
            style={{
              display: "block",
              fontSize: 12,
              color: "#aaa",
              marginBottom: 6,
              fontWeight: 500,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}
          >
            Preferred Subject
          </label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {SUBJECTS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => setSubject(s.id)}
                style={{
                  padding: "8px 14px",
                  borderRadius: 8,
                  border: subject === s.id ? "2px solid #7c3aed" : "1px solid #333",
                  background: subject === s.id ? "#2d1b69" : "#16213e",
                  color: subject === s.id ? "#c4b5fd" : "#888",
                  fontSize: 14,
                  fontWeight: subject === s.id ? 600 : 400,
                  cursor: "pointer",
                  transition: "all 0.15s",
                }}
              >
                {s.emoji} {s.label}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p style={{ fontSize: 13, color: "#f87171", textAlign: "center" }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={saving || !name.trim()}
          style={{
            width: "100%",
            padding: "14px",
            borderRadius: 12,
            border: "none",
            background:
              saving || !name.trim()
                ? "#4a4a6a"
                : "linear-gradient(135deg, #7c3aed, #a78bfa)",
            color: saving || !name.trim() ? "#666" : "#fff",
            fontSize: 16,
            fontWeight: 600,
            cursor: saving || !name.trim() ? "not-allowed" : "pointer",
            letterSpacing: "0.02em",
            transition: "transform 0.15s, box-shadow 0.15s",
            boxShadow:
              saving || !name.trim()
                ? "none"
                : "0 4px 24px rgba(124, 58, 237, 0.35)",
            marginTop: 4,
          }}
          onMouseEnter={(e) => {
            if (!saving && name.trim()) {
              e.target.style.transform = "scale(1.02)";
              e.target.style.boxShadow = "0 6px 32px rgba(124, 58, 237, 0.5)";
            }
          }}
          onMouseLeave={(e) => {
            e.target.style.transform = "scale(1)";
            e.target.style.boxShadow = "0 4px 24px rgba(124, 58, 237, 0.35)";
          }}
        >
          {saving ? "Creating Profile..." : "Start Learning"}
        </button>
      </form>

      <p
        style={{
          fontSize: 11,
          color: "#555",
          textAlign: "center",
          marginTop: 24,
          lineHeight: 1.6,
        }}
      >
        CBSE · Class 3 – 10 · Math, Science, English, Social Studies
      </p>
    </div>
  );
}
