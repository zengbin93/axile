import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { AccountEditPage } from '../src/pages/AccountEditPage'
import { AccountEditNotificationPage } from '../src/pages/AccountEditNotificationPage'
import { useDomainStore } from '../src/stores/domain'
import { useChannelCatalogStore } from '../src/stores/channels'
import '../src/styles/theme.css'

useDomainStore.setState({ portfolios: [], accounts: [] })
useChannelCatalogStore.setState({ channels: [], loading: false })
const path = new URLSearchParams(location.search).get('editor') ? '/accounts/1/edit/notification' : '/accounts/1/edit'
const router = createMemoryRouter([
  { path: '/accounts/:id/edit', element: <AccountEditPage /> },
  { path: '/accounts/:id/edit/notification', element: <AccountEditNotificationPage /> },
], { initialEntries: [path] })
createRoot(document.getElementById('root')!).render(<RouterProvider router={router} />)
