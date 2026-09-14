import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { TicketListPage } from "./pages/TicketListPage";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/tickets"
          element={
            <RequireAuth>
              <TicketListPage />
            </RequireAuth>
          }
        />
        <Route
          path="/tickets/:ticketId"
          element={
            <RequireAuth>
              <TicketDetailPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/tickets" replace />} />
      </Routes>
    </AuthProvider>
  );
}
