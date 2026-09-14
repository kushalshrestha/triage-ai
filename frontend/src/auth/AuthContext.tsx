import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { fetchCurrentUser, login as apiLogin, register as apiRegister, setAuthToken } from "../api/client";
import type { UserRead } from "../api/types";

const TOKEN_STORAGE_KEY = "triageai.token";

interface AuthContextValue {
  user: UserRead | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
    if (!storedToken) {
      setIsLoading(false);
      return;
    }
    setAuthToken(storedToken);
    fetchCurrentUser()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setAuthToken(null);
      })
      .finally(() => setIsLoading(false));
  }, []);

  async function login(email: string, password: string): Promise<void> {
    const token = await apiLogin(email, password);
    localStorage.setItem(TOKEN_STORAGE_KEY, token.access_token);
    setAuthToken(token.access_token);
    setUser(await fetchCurrentUser());
  }

  async function register(email: string, password: string): Promise<void> {
    await apiRegister(email, password);
    await login(email, password);
  }

  function logout(): void {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setAuthToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
