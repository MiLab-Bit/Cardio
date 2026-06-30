import React from 'react'
import { ChatProvider } from './store'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import AgentPipeline from './components/AgentPipeline'
import ChatArea from './components/ChatArea'
import InputBar from './components/InputBar'
import RightDrawer from './components/RightDrawer'

function App() {
  const [drawerOpen, setDrawerOpen] = React.useState(true)

  return (
    <ChatProvider>
      <div className="app-layout">
        <Sidebar />
        <main className="main-area">
          <TopBar onOpenDrawer={() => setDrawerOpen(!drawerOpen)} />
          <AgentPipeline />
          <ChatArea />
          <InputBar />
        </main>
        {drawerOpen && <RightDrawer onClose={() => setDrawerOpen(false)} />}
      </div>
    </ChatProvider>
  )
}

export default App
