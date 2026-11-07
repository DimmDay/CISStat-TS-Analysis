"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  ReactNode,
} from "react";
import { authMe, authCommand, AuthSession } from "../lib/authClient";
type State = {
  status: "loading" | "anonymous" | "authenticated" | "unavailable";
  session: AuthSession | null;
};
type Context = State & {
  refresh: () => Promise<AuthSession | null>;
  logout: () => Promise<void>;
};
const AuthContext = createContext<Context | null>(null),
  reloadPage = () => window.location.reload();
export function AuthProvider({
  children,
  onExternalSessionChange = reloadPage,
}: {
  children: ReactNode;
  onExternalSessionChange?: () => void;
}) {
  const [state, setState] = useState<State>({
      status: "loading",
      session: null,
    }),
    generation = useRef(0),
    snapshot = useRef<string | undefined>(undefined);
  const read = useCallback(
    async (external = false) => {
      const current = ++generation.current;
      try {
        const session = await authMe();
        if (current === generation.current) {
          const next = session
              ? [
                  session.subject_id,
                  session.account_id,
                  session.auth_session_id,
                  session.entitlement_version,
                ].join(":")
              : "anonymous",
            changed =
              snapshot.current !== undefined && snapshot.current !== next;
          snapshot.current = next;
          setState({
            status: session ? "authenticated" : "anonymous",
            session,
          });
          if (external && changed) onExternalSessionChange();
        }
        return current === generation.current ? session : null;
      } catch (error) {
        if (current === generation.current)
          setState({ status: "unavailable", session: null });
        throw error;
      }
    },
    [onExternalSessionChange],
  );
  const refresh = useCallback(() => read(false), [read]);
  const logout = useCallback(async () => {
    await authCommand("logout");
    generation.current++;
    snapshot.current = "anonymous";
    setState({ status: "anonymous", session: null });
  }, []);
  useEffect(() => {
    const update = () => {
      void read(true).catch(() => {});
    };
    update();
    window.addEventListener("focus", update);
    return () => {
      generation.current++;
      window.removeEventListener("focus", update);
    };
  }, [read]);
  return (
    <AuthContext.Provider value={{ ...state, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("AuthProvider required");
  return context;
}
