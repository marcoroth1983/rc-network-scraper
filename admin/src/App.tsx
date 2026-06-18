import { Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import { RequireAdmin } from './routes/RequireAdmin';
import { AppShell } from './components/AppShell';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAdmin>
            <AppShell />
          </RequireAdmin>
        }
      >
        <Route index element={<div className="text-text-primary">Übersicht (Stub)</div>} />
        <Route path="metrics" element={<div className="text-text-primary">Metriken (Stub)</div>} />
        <Route path="llm" element={<div className="text-text-primary">LLM-Kaskade (Stub)</div>} />
        <Route path="users" element={<div className="text-text-primary">Nutzer (Stub)</div>} />
      </Route>
    </Routes>
  );
}
