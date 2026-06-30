import { useState, useEffect, useCallback } from "react";

const API = "/api/children";
const SUBJECTS = [
  { id: null, label: "All", icon: "📊" },
  { id: "math", label: "Math", icon: "🔢" },
  { id: "science", label: "Science", icon: "🔬" },
  { id: "english", label: "English", icon: "📖" },
  { id: "social_studies", label: "Social Studies", icon: "🌍" },
];

const MISTAKE_COLORS = {
  conceptual: "#ef4444",
  procedural: "#f59e0b",
  careless: "#3b82f6",
};
const MISTAKE_LABELS = {
  conceptual: "Conceptual",
  procedural: "Procedural",
  careless: "Careless",
};

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function masteryColor(score) {
  if (score >= 0.8) return "bg-green-500 text-white";
  if (score >= 0.6) return "bg-green-300 text-green-900";
  if (score >= 0.4) return "bg-yellow-300 text-yellow-900";
  if (score >= 0.2) return "bg-orange-400 text-white";
  return "bg-red-500 text-white";
}

function masteryLabel(score) {
  if (score >= 0.8) return "Strong";
  if (score >= 0.6) return "Good";
  if (score >= 0.4) return "Fair";
  if (score >= 0.2) return "Weak";
  return "Needs work";
}

// ── Simple SVG pie slice ───────────────────────────────────────────
function PieSlice({ cx, cy, r, startAngle, endAngle, color, label, pct }) {
  const toRad = (deg) => (deg - 90) * (Math.PI / 180);
  const s = toRad(startAngle);
  const e = toRad(endAngle);
  const x1 = cx + r * Math.cos(s);
  const y1 = cy + r * Math.sin(s);
  const x2 = cx + r * Math.cos(e);
  const y2 = cy + r * Math.sin(e);
  const large = endAngle - startAngle > 180 ? 1 : 0;
  const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
  // Label on the midpoint radius
  const mid = toRad((startAngle + endAngle) / 2);
  const lr = r * 0.65;
  const lx = cx + lr * Math.cos(mid);
  const ly = cy + lr * Math.sin(mid);

  return (
    <g>
      <path d={path} fill={color} stroke="#1e1e2e" strokeWidth="2" />
      {pct > 5 && (
        <text
          x={lx}
          y={ly}
          fill="white"
          fontSize="12"
          fontWeight="bold"
          textAnchor="middle"
          dominantBaseline="central"
          style={{ pointerEvents: "none" }}
        >
          {pct}%
        </text>
      )}
    </g>
  );
}

function MistakePieChart({ mistakes }) {
  const total = mistakes.length;
  if (total === 0)
    return <p className="text-gray-500 text-sm">No mistakes recorded</p>;

  const counts = {};
  for (const m of mistakes) {
    counts[m.error_type] = (counts[m.error_type] || 0) + 1;
  }

  const entries = ["conceptual", "procedural", "careless"]
    .filter((t) => counts[t])
    .map((t) => ({ type: t, count: counts[t], pct: Math.round((counts[t] / total) * 100) }));

  const r = 70;
  const cx = 80;
  const cy = 80;
  let current = 0;
  const slices = entries.map((e) => {
    const deg = (e.count / total) * 360;
    const slice = { ...e, startAngle: current, endAngle: current + deg };
    current += deg;
    return slice;
  });

  return (
    <div className="flex items-center gap-4">
      <svg width={160} height={160} viewBox="0 0 160 160">
        {slices.map((s) => (
          <PieSlice
            key={s.type}
            cx={cx}
            cy={cy}
            r={r}
            startAngle={s.startAngle}
            endAngle={s.endAngle}
            color={MISTAKE_COLORS[s.type]}
            pct={s.pct}
          />
        ))}
        {total === 0 && (
          <circle cx={cx} cy={cy} r={r} fill="#374151" />
        )}
      </svg>
      <div className="space-y-1 text-xs">
        {entries.map((e) => (
          <div key={e.type} className="flex items-center gap-2">
            <span
              className="inline-block w-3 h-3 rounded-sm"
              style={{ background: MISTAKE_COLORS[e.type] }}
            />
            <span className="text-gray-300">{MISTAKE_LABELS[e.type]}</span>
            <span className="text-gray-400 ml-auto">{e.count}</span>
          </div>
        ))}
        <div className="pt-1 text-gray-500 text-[10px]">{total} total</div>
      </div>
    </div>
  );
}

// ── WhatsApp share ──────────────────────────────────────────────────
function buildWeekSummary(sessions, mastery, mistakes) {
  const lines = [
    "📚 *AI Tutor — Weekly Summary*",
    "",
  ];

  if (sessions.length > 0) {
    const bySubject = {};
    let totalMin = 0;
    for (const s of sessions) {
      bySubject[s.subject_name] = (bySubject[s.subject_name] || 0) + 1;
      totalMin += s.duration_minutes || 0;
    }
    lines.push(`*Sessions:* ${sessions.length} (${Math.round(totalMin)} min)`);
    for (const [subj, count] of Object.entries(bySubject)) {
      lines.push(`  ${subj}: ${count} session${count > 1 ? "s" : ""}`);
    }
    lines.push("");
  }

  if (mastery.length > 0) {
    lines.push("*Topic Mastery:*");
    const weak = mastery.filter((m) => m.score < 0.5);
    if (weak.length > 0) {
      lines.push(`  Needs practice: ${weak.map((m) => m.topic).join(", ")}`);
    }
    const strong = mastery.filter((m) => m.score >= 0.8);
    if (strong.length > 0) {
      lines.push(`  Doing well: ${strong.map((m) => m.topic).join(", ")}`);
    }
    lines.push("");
  }

  if (mistakes.length > 0) {
    const byType = {};
    for (const m of mistakes) {
      byType[m.error_type] = (byType[m.error_type] || 0) + 1;
    }
    lines.push("*Mistakes:*");
    for (const [type, count] of Object.entries(byType)) {
      lines.push(`  ${MISTAKE_LABELS[type] || type}: ${count}`);
    }
    lines.push("");
  }

  lines.push("Generated by AI Tutor 🤖");
  return lines.join("\n");
}

function WhatsAppShare({ sessions, mastery, mistakes }) {
  const handleShare = () => {
    const text = buildWeekSummary(sessions, mastery, mistakes);
    const url = `https://wa.me/?text=${encodeURIComponent(text)}`;
    window.open(url, "_blank");
  };

  return (
    <button
      onClick={handleShare}
      className="w-full bg-green-600 hover:bg-green-500 text-white font-medium py-3 px-4 rounded-xl flex items-center justify-center gap-2 transition-colors cursor-pointer"
    >
      <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
      </svg>
      Share on WhatsApp
    </button>
  );
}

// ── Loading / error states ─────────────────────────────────────────
function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-8 h-8 border-4 border-gray-600 border-t-purple-400 rounded-full animate-spin" />
    </div>
  );
}

// ── Main Dashboard ─────────────────────────────────────────────────
export default function Dashboard() {
  const params = new URLSearchParams(window.location.search);
  const childId = params.get("child_id") || "local_child";
  const childName = params.get("name") || `Child ${childId.slice(0, 6)}`;

  const [subject, setSubject] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [mastery, setMastery] = useState([]);
  const [mistakes, setMistakes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    const qs = subject ? `?subject=${subject}` : "";
    try {
      const [sRes, mRes, errRes] = await Promise.all([
        fetch(`${API}/${childId}/sessions${qs}`),
        fetch(`${API}/${childId}/mastery${qs}`),
        fetch(`${API}/${childId}/mistakes${qs}`),
      ]);
      if (!sRes.ok || !mRes.ok || !errRes.ok)
        throw new Error("Failed to fetch dashboard data");
      const [sData, mData, eData] = await Promise.all([
        sRes.json(),
        mRes.json(),
        errRes.json(),
      ]);
      setSessions(sData.sessions || []);
      setMastery(mData.mastery || []);
      setMistakes(eData.mistakes || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [childId, subject]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return (
    <div className="min-h-screen bg-[#1e1e2e] text-gray-100 font-sans pb-24">
      {/* Header */}
      <header className="sticky top-0 z-10 bg-[#1a1a2e]/95 backdrop-blur border-b border-gray-800 px-4 py-4">
        <div className="max-w-lg mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-purple-300">AI Tutor</h1>
            <p className="text-sm text-gray-400">Parent Dashboard</p>
          </div>
          <div className="text-right">
            <p className="text-sm font-medium">{childName}</p>
            <p className="text-xs text-gray-500">ID: {childId.slice(0, 8)}</p>
          </div>
        </div>
      </header>

      {/* Subject Tabs */}
      <div className="max-w-lg mx-auto px-4 pt-4">
        <div className="flex gap-1 overflow-x-auto pb-2 scrollbar-none">
          {SUBJECTS.map((s) => (
            <button
              key={s.label}
              onClick={() => setSubject(s.id)}
              className={`shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                subject === s.id
                  ? "bg-purple-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              {s.icon} {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-lg mx-auto px-4 pt-4 space-y-4">
        {error && (
          <div className="bg-red-900/50 border border-red-700 rounded-xl p-4 text-sm text-red-200">
            {error}
            <button
              onClick={fetchAll}
              className="ml-2 underline cursor-pointer"
            >
              Retry
            </button>
          </div>
        )}

        {loading && <LoadingSpinner />}

        {!loading && !error && (
          <>
            {/* Session History */}
            <Card title={`Sessions (${sessions.length})`}>
              {sessions.length === 0 ? (
                <p className="text-gray-500 text-sm py-2">
                  No sessions yet. Start a tutoring session to see it here.
                </p>
              ) : (
                <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                  {sessions.map((s) => (
                    <div
                      key={s.id}
                      className="bg-gray-800/50 rounded-lg p-3 text-sm"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-purple-300">
                          {s.subject_name}
                        </span>
                        <span className="text-gray-500 text-xs">
                          {s.duration_minutes != null
                            ? `${s.duration_minutes} min`
                            : "—"}
                        </span>
                      </div>
                      <p className="text-gray-400 text-xs mt-0.5">
                        {fmtDate(s.started_at)}
                      </p>
                      {s.topics_covered?.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {s.topics_covered.map((t, i) => (
                            <span
                              key={i}
                              className="bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded text-[10px]"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Topic Mastery Heatmap */}
            <Card title={`Topic Mastery — ${subject || "All"}`}>
              {mastery.length === 0 ? (
                <p className="text-gray-500 text-sm py-2">
                  No topics assessed yet.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {mastery.map((m) => (
                    <div
                      key={m.topic}
                      className="flex items-center gap-3 text-sm"
                    >
                      <span className="w-32 shrink-0 text-gray-300 truncate">
                        {m.topic}
                      </span>
                      <div className="flex-1 h-6 rounded-md overflow-hidden bg-gray-800">
                        <div
                          className={`h-full rounded-md ${masteryColor(m.score)}`}
                          style={{ width: `${Math.round(m.score * 100)}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-xs text-gray-400 shrink-0">
                        {masteryLabel(m.score)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Mistake Breakdown */}
            <Card title="Mistake Breakdown">
              <MistakePieChart mistakes={mistakes} />
            </Card>

            {/* WhatsApp Share */}
            <Card>
              <WhatsAppShare
                sessions={sessions}
                mastery={mastery}
                mistakes={mistakes}
              />
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

// ── Reusable card wrapper ──────────────────────────────────────────
function Card({ title, children }) {
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-4">
      {title && (
        <h2 className="text-sm font-semibold text-gray-300 mb-3 uppercase tracking-wide">
          {title}
        </h2>
      )}
      {children}
    </div>
  );
}
