import { Route, Routes } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import { RequireAdmin } from './routes/RequireAdmin';
import { AppShell } from './components/AppShell';
import { MetricsPage } from './pages/MetricsPage';
import { LlmPage } from './pages/LlmPage';
import { UsersPage } from './pages/UsersPage';

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
        <Route index element={<MetricsPage />} />
        <Route path="metrics" element={<MetricsPage />} />
        <Route path="llm" element={<LlmPage />} />
        <Route path="users" element={<UsersPage />} />
      </Route>
    </Routes>
  );
}
