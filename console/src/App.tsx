import { useState } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Login } from "./auth/Login";
import { Shell, type ViewKey } from "./components/Shell";
import { Dashboard } from "./views/Dashboard";
import { Orchestrator } from "./views/Orchestrator";
import { Router } from "./views/Router";
import { Budget } from "./views/Budget";
import { NeuralMap } from "./views/NeuralMap";
import { Kanban } from "./views/Kanban";

function Authed() {
  const [view, setView] = useState<ViewKey>("dashboard");
  return (
    <Shell view={view} onNavigate={setView}>
      {view === "dashboard" && <Dashboard />}
      {view === "kanban" && <Kanban />}
      {view === "orchestrator" && <Orchestrator />}
      {view === "router" && <Router />}
      {view === "budget" && <Budget />}
      {view === "map" && <NeuralMap />}
    </Shell>
  );
}

function Gate() {
  const { token } = useAuth();
  return token ? <Authed /> : <Login />;
}

export function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  );
}
