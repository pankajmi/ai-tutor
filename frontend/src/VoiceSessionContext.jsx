import { createContext, useContext } from "react";

export const VoiceSessionContext = createContext(null);

export function useVoiceSession() {
  const ctx = useContext(VoiceSessionContext);
  if (!ctx) throw new Error("useVoiceSession must be used within VoiceSessionShell");
  return ctx;
}
