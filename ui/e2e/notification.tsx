import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { PortfolioEditPage } from '../src/pages/PortfolioEditPage'
import { InitWizard } from '../src/features/init/InitWizard'
import { AccountEditPage } from '../src/pages/AccountEditPage'
import { AccountEditNotificationPage } from '../src/pages/AccountEditNotificationPage'
import { useDomainStore } from '../src/stores/domain'
import { useChannelCatalogStore } from '../src/stores/channels'
import '../src/styles/theme.css'

useDomainStore.setState({ portfolios: [], accounts: [] })
useChannelCatalogStore.setState({ channels: [], loading: false })
const params = new URLSearchParams(location.search)
const path = params.has('portfolio') ? '/portfolios/1/edit' : params.has('system') ? '/system' : params.has('editor') ? '/accounts/1/edit/notification' : '/accounts/1/edit'
const router = createMemoryRouter([
  { path: '/portfolios/:id/edit', element: <PortfolioEditPage /> },
  { path: '/system', element: <InitWizard mode="edit" initial={{ sqlalchemy_database_uri: '', exe_err_feishu_key: '', system_execution_notification_mode: 'function', system_execution_notification_code: 'def notify(context):\n    pass\n', environment: 'local', app_log_dir: './logs', axile_log_rotation: '1 day', algorithm_modules: [], algorithm_directories: [] }} /> },
  { path: '/accounts/:id/edit', element: <AccountEditPage /> },
  { path: '/accounts/:id/edit/notification', element: <AccountEditNotificationPage /> },
], { initialEntries: [path] })
createRoot(document.getElementById('root')!).render(<RouterProvider router={router} />)
