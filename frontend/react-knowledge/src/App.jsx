import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ToastProvider } from './components/Toast';
import { Dashboard } from './pages/Dashboard';
import { SmartUpload } from './pages/SmartUpload';
import { ProductDetail } from './pages/ProductDetail';
import { ReviewQueue } from './pages/ReviewQueue';
import { Documents } from './pages/Documents';
import { PortfolioDetail } from './pages/PortfolioDetail';

function Layout({ children }) {
  return (
    <div className="py-4">
      {children}
    </div>
  );
}

function App() {
  return (
    <BrowserRouter basename="/base-conhecimento">
      <ToastProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/upload" element={<SmartUpload />} />
            <Route path="/product/:id" element={<ProductDetail />} />
            <Route path="/portfolios/:id" element={<PortfolioDetail />} />
            <Route path="/portfolio/:id" element={<PortfolioDetail />} />
            <Route path="/review" element={<ReviewQueue />} />
            <Route path="/documents" element={<Documents />} />
          </Routes>
        </Layout>
      </ToastProvider>
    </BrowserRouter>
  );
}

export default App;
