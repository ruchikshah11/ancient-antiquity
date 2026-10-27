import * as React from 'react';
import { Outlet, Route, Routes } from 'react-router-dom';
import { Empty, Loader, RequireAuth } from './components/Common';
import Footer from './components/Footer';
import Navbar from './components/Navbar';
import Home from './pages/client/Home';

// Pages load on demand (code splitting): only the shell and the home page are in the main bundle.
// Admin screens, the QR scanner, reports, the place editor and invoices never reach visitors who don't open them.
const AdminBookings = React.lazy(() => import('./pages/admin/AdminBookings'));
const AdminLayout = React.lazy(() => import('./pages/admin/AdminLayout'));
const AdminMuseums = React.lazy(() => import('./pages/admin/AdminMuseums'));
const AdminReviews = React.lazy(() => import('./pages/admin/AdminReviews'));
const AdminUsers = React.lazy(() => import('./pages/admin/AdminUsers'));
const CheckIn = React.lazy(() => import('./pages/admin/CheckIn'));
const CounterSale = React.lazy(() => import('./pages/admin/CounterSale'));
const Dashboard = React.lazy(() => import('./pages/admin/Dashboard'));
const GroupRequests = React.lazy(() => import('./pages/admin/GroupRequests'));
const MuseumForm = React.lazy(() => import('./pages/admin/MuseumForm'));
const Reports = React.lazy(() => import('./pages/admin/Reports'));
const Checkout = React.lazy(() => import('./pages/client/Checkout'));
const ForgotPassword = React.lazy(() => import('./pages/client/ForgotPassword'));
const GroupRequest = React.lazy(() => import('./pages/client/GroupRequest'));
const Invoice = React.lazy(() => import('./pages/client/Invoice'));
const ResetPassword = React.lazy(() => import('./pages/client/ResetPassword'));
const Contact = React.lazy(() => import('./pages/client/Legal').then((m) => ({ default: m.Contact })));
const Privacy = React.lazy(() => import('./pages/client/Legal').then((m) => ({ default: m.Privacy })));
const RefundPolicy = React.lazy(() => import('./pages/client/Legal').then((m) => ({ default: m.RefundPolicy })));
const Terms = React.lazy(() => import('./pages/client/Legal').then((m) => ({ default: m.Terms })));
const SupportMessages = React.lazy(() => import('./pages/admin/SupportMessages'));
const Login = React.lazy(() => import('./pages/client/Auth').then((m) => ({ default: m.Login })));
const Register = React.lazy(() => import('./pages/client/Auth').then((m) => ({ default: m.Register })));
const MuseumDetail = React.lazy(() => import('./pages/client/MuseumDetail'));
const Museums = React.lazy(() => import('./pages/client/Museums'));
const MyBookings = React.lazy(() => import('./pages/client/MyBookings'));
const Profile = React.lazy(() => import('./pages/client/Profile'));
const Ticket = React.lazy(() => import('./pages/client/Ticket'));
const MapPage = React.lazy(() => import('./pages/client/MapPage'));
const Favourites = React.lazy(() => import('./pages/client/Favourites'));
const TripPlanner = React.lazy(() => import('./pages/client/TripPlanner'));
const Promotions = React.lazy(() => import('./pages/admin/Promotions'));
const AuditLog = React.lazy(() => import('./pages/admin/AuditLog'));
const Passes = React.lazy(() => import('./pages/client/Passes'));
const PassDetail = React.lazy(() => import('./pages/client/PassDetail'));
const AdminPasses = React.lazy(() => import('./pages/admin/AdminPasses'));
const Occupancy = React.lazy(() => import('./pages/admin/Occupancy'));
const AgentPortal = React.lazy(() => import('./pages/agent/AgentPortal'));
const Kiosk = React.lazy(() => import('./pages/kiosk/Kiosk'));
const Partners = React.lazy(() => import('./pages/admin/Partners'));
const Settlements = React.lazy(() => import('./pages/admin/Settlements'));
const Funnel = React.lazy(() => import('./pages/admin/Funnel'));
const About = React.lazy(() => import('./pages/client/About'));
const Membership = React.lazy(() => import('./pages/client/Membership'));
const Donate = React.lazy(() => import('./pages/client/Donate'));
const DonationReceipt = React.lazy(() => import('./pages/client/DonationReceipt'));
const AdminAddOns = React.lazy(() => import('./pages/admin/AdminAddOns'));
const AdminMemberships = React.lazy(() => import('./pages/admin/AdminMemberships'));
const AdminDonations = React.lazy(() => import('./pages/admin/AdminDonations'));
const SchoolPortal = React.lazy(() => import('./pages/client/SchoolPortal'));
const SchoolTrips = React.lazy(() => import('./pages/admin/SchoolTrips'));
const SiteSettingsPage = React.lazy(() => import('./pages/admin/SiteSettings'));
const PricingInsights = React.lazy(() => import('./pages/admin/PricingInsights'));
const Exports = React.lazy(() => import('./pages/admin/Exports'));
const PartnerPortal = React.lazy(() => import('./pages/partner/PartnerPortal'));
const Events = React.lazy(() => import('./pages/client/Events'));
const EventDetail = React.lazy(() => import('./pages/client/EventDetail'));
const AdminEvents = React.lazy(() => import('./pages/admin/AdminEvents'));

class ClientLayout extends React.Component {
  public render(): React.ReactNode {
    return (
      <div className="d-flex flex-column min-vh-100">
        <Navbar />
        <main className="flex-grow-1">
          <React.Suspense fallback={<Loader />}>
            <Outlet />
          </React.Suspense>
        </main>
        <Footer />
      </div>
    );
  }
}

export default class App extends React.Component {
  public render(): React.ReactNode {
    return (
      <React.Suspense fallback={<Loader />}>
        <Routes>
          <Route element={<ClientLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/museums" element={<Museums />} />
            <Route path="/museums/:slug" element={<MuseumDetail />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/checkout/:reference" element={<RequireAuth><Checkout /></RequireAuth>} />
            <Route path="/tickets/:reference" element={<RequireAuth><Ticket /></RequireAuth>} />
            <Route path="/my-bookings" element={<RequireAuth><MyBookings /></RequireAuth>} />
            <Route path="/profile" element={<RequireAuth><Profile /></RequireAuth>} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password/:uid/:token" element={<ResetPassword />} />
            <Route path="/invoices/:reference" element={<RequireAuth><Invoice /></RequireAuth>} />
            <Route path="/group-request/:slug" element={<RequireAuth><GroupRequest /></RequireAuth>} />
            <Route path="/about" element={<About />} />
            <Route path="/membership" element={<Membership />} />
            <Route path="/donate" element={<Donate />} />
            <Route path="/schools" element={<SchoolPortal />} />
            <Route path="/donations/:receipt" element={<DonationReceipt />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/refund-policy" element={<RefundPolicy />} />
            <Route path="/contact" element={<Contact />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/favourites" element={<RequireAuth><Favourites /></RequireAuth>} />
            <Route path="/trips" element={<RequireAuth><TripPlanner /></RequireAuth>} />
            <Route path="/trips/:id" element={<RequireAuth><TripPlanner /></RequireAuth>} />
            <Route path="/passes" element={<Passes />} />
            <Route path="/passes/:slug" element={<PassDetail />} />
            <Route path="/events" element={<Events />} />
            <Route path="/events/:slug" element={<EventDetail />} />
            <Route path="/partner" element={<RequireAuth><PartnerPortal /></RequireAuth>} />
            <Route path="/agent" element={<RequireAuth><AgentPortal /></RequireAuth>} />
            <Route path="*" element={<div className="container py-5"><Empty title="Page not found" /></div>} />
          </Route>

          <Route path="/admin" element={<RequireAuth panel><AdminLayout /></RequireAuth>}>
            <Route index element={<Dashboard />} />
            <Route path="bookings" element={<AdminBookings />} />
            <Route path="checkin" element={<CheckIn />} />
            <Route path="counter" element={<CounterSale />} />
            <Route path="group-requests" element={<GroupRequests />} />
            <Route path="reports" element={<Reports />} />
            <Route path="support" element={<SupportMessages />} />
            <Route path="promotions" element={<Promotions />} />
            <Route path="audit" element={<RequireAuth admin><AuditLog /></RequireAuth>} />
            <Route path="museums" element={<RequireAuth admin><AdminMuseums /></RequireAuth>} />
            <Route path="museums/new" element={<RequireAuth admin><MuseumForm /></RequireAuth>} />
            <Route path="museums/:slug/edit" element={<RequireAuth admin><MuseumForm /></RequireAuth>} />
            <Route path="users" element={<RequireAuth admin><AdminUsers /></RequireAuth>} />
            <Route path="reviews" element={<RequireAuth admin><AdminReviews /></RequireAuth>} />
            <Route path="occupancy" element={<Occupancy />} />
            <Route path="settlements" element={<Settlements />} />
            <Route path="funnel" element={<Funnel />} />
            <Route path="events" element={<AdminEvents />} />
            <Route path="addons" element={<AdminAddOns />} />
            <Route path="school-trips" element={<SchoolTrips />} />
            <Route path="settings" element={<RequireAuth admin><SiteSettingsPage /></RequireAuth>} />
            <Route path="pricing" element={<PricingInsights />} />
            <Route path="exports" element={<Exports />} />
            <Route path="memberships" element={<RequireAuth admin><AdminMemberships /></RequireAuth>} />
            <Route path="donations" element={<RequireAuth admin><AdminDonations /></RequireAuth>} />
            <Route path="passes" element={<RequireAuth admin><AdminPasses /></RequireAuth>} />
            <Route path="partners" element={<RequireAuth admin><Partners /></RequireAuth>} />
          </Route>

          {/* Self-service kiosk: full screen, its own sign-in, no site header/footer. */}
          <Route path="/kiosk" element={<Kiosk />} />
        </Routes>
      </React.Suspense>
    );
  }
}
