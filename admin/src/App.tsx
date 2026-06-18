import { Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import { RequireAdmin } from './routes/RequireAdmin';

function AppShell() {
  return <div className="min-h-dvh bg-bg-app text-text-primary">App Shell (Task 3)</div>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/*"
        element={
          <RequireAdmin>
            <AppShell />
          </RequireAdmin>
        }
      />
    </Routes>
  );
}
