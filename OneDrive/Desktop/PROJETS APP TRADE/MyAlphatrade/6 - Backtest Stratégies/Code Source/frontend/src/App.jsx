import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { AuthProvider, useAuth } from '@/lib/AuthContext';
import UserNotRegisteredError from '@/components/UserNotRegisteredError';
import ScrollToTop from './components/ScrollToTop';
import ProtectedRoute from '@/components/ProtectedRoute';
import { AssetProvider } from '@/lib/AssetContext';

// Auth pages
import Login from '@/pages/Login';
import Register from '@/pages/Register';
import ForgotPassword from '@/pages/ForgotPassword';
import ResetPassword from '@/pages/ResetPassword';

// App pages
import Layout from '@/components/Layout';
import MarketData from '@/pages/MarketData';
import Strategies from '@/pages/Strategies';
import Backtesting from '@/pages/Backtesting';
import PaperTrading from '@/pages/PaperTrading';
import Signals from '@/pages/Signals';
import AssetManagement from '@/pages/AssetManagement';
import AIDesigner from '@/pages/AIDesigner';
import Settings from '@/pages/Settings';
import { AISettingsProvider } from '@/lib/AISettingsContext';
import { AlphaTradeConnectionProvider } from '@/lib/AlphaTradeConnectionContext';

const AuthenticatedApp = () => {
  const { isLoadingAuth, isLoadingPublicSettings, authError, navigateToLogin } = useAuth();

  if (isLoadingPublicSettings || isLoadingAuth) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-[#0a0e17]">
        <div className="w-8 h-8 border-4 border-amber-500/20 border-t-amber-500 rounded-full animate-spin"></div>
      </div>
    );
  }

  if (authError) {
    if (authError.type === 'user_not_registered') {
      return <UserNotRegisteredError />;
    } else if (authError.type === 'auth_required') {
      navigateToLogin();
      return null;
    }
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      <Route element={<ProtectedRoute unauthenticatedElement={<Navigate to="/login" replace />} />}>
        <Route element={<Layout />}>
          <Route path="/" element={<MarketData />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/backtesting" element={<Backtesting />} />
          <Route path="/paper-trading" element={<PaperTrading />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/ai-designer" element={<AIDesigner />} />
          <Route path="/assets" element={<AssetManagement />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Route>

      <Route path="*" element={<PageNotFound />} />
    </Routes>
  );
};

function App() {
  return (
    <AuthProvider>
      <QueryClientProvider client={queryClientInstance}>
        <Router>
          <ScrollToTop />
          <AssetProvider>
            <AISettingsProvider>
              <AlphaTradeConnectionProvider>
                <AuthenticatedApp />
              </AlphaTradeConnectionProvider>
            </AISettingsProvider>
          </AssetProvider>
        </Router>
        <Toaster />
      </QueryClientProvider>
    </AuthProvider>
  )
}

export default App