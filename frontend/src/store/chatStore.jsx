import React, { createContext, useContext, useReducer, useCallback } from 'react'

// Agent 名称映射
export const AGENT_NAMES = ['提取', '研究', '分层', '策略', '审核']

// 初始状态
const initialState = {
  messages: [],
  taskId: null,
  agentProgress: {
    extract: 'pending',
    research: 'pending',
    segment: 'pending',
    strategy: 'pending',
    critic: 'pending',
  },
  isTyping: false,
  outputFiles: [],
  activeAgentTabs: {},
  inputDisabled: false,
}

// Action types
export const ACTIONS = {
  ADD_USER_MESSAGE: 'ADD_USER_MESSAGE',
  ADD_AGENT_MESSAGE: 'ADD_AGENT_MESSAGE',
  SET_AGENT_PROGRESS: 'SET_AGENT_PROGRESS',
  UPDATE_AGENT_REPORT: 'UPDATE_AGENT_REPORT',
  SET_AGENT_MESSAGE_TIME: 'SET_AGENT_MESSAGE_TIME',
  SET_ACTIVE_AGENT_TAB: 'SET_ACTIVE_AGENT_TAB',
  SET_INPUT_DISABLED: 'SET_INPUT_DISABLED',
  SET_TYPING: 'SET_TYPING',
  ADD_OUTPUT_FILE: 'ADD_OUTPUT_FILE',
  RESET: 'RESET',
}

// Reducer
function chatReducer(state, action) {
  switch (action.type) {
    case ACTIONS.ADD_USER_MESSAGE:
      return { ...state, messages: [...state.messages, action.payload] }

    case ACTIONS.ADD_AGENT_MESSAGE:
      return {
        ...state,
        messages: [...state.messages, action.payload],
        activeAgentTabs: {
          ...state.activeAgentTabs,
          [action.payload.id]: 0,
        },
      }

    case ACTIONS.SET_AGENT_PROGRESS:
      return {
        ...state,
        agentProgress: {
          ...state.agentProgress,
          [action.payload.agent]: action.payload.status,
        },
      }

    case ACTIONS.UPDATE_AGENT_REPORT: {
      const { msgId, agent, reportData } = action.payload
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === msgId && m.type === 'agent'
            ? { ...m, reports: { ...m.reports, [agent]: reportData } }
            : m
        ),
      }
    }

    case ACTIONS.SET_AGENT_MESSAGE_TIME:
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.payload.msgId
            ? { ...m, time: action.payload.time }
            : m
        ),
      }

    case ACTIONS.SET_ACTIVE_AGENT_TAB:
      return {
        ...state,
        activeAgentTabs: {
          ...state.activeAgentTabs,
          [action.payload.msgId]: action.payload.tabIdx,
        },
      }

    case ACTIONS.SET_INPUT_DISABLED:
      return { ...state, inputDisabled: action.payload }

    case ACTIONS.SET_TYPING:
      return { ...state, isTyping: action.payload }

    case ACTIONS.ADD_OUTPUT_FILE:
      return { ...state, outputFiles: [...state.outputFiles, action.payload] }

    case ACTIONS.RESET:
      return initialState

    default:
      return state
  }
}

// Context
const ChatContext = createContext(null)

// Provider 组件（JSX 写在这里）
export function ChatProvider({ children }) {
  const [state, dispatch] = useReducer(chatReducer, initialState)

  const value = { state, dispatch, ACTIONS }
  return (
    <ChatContext.Provider value={value}>
      {children}
    </ChatContext.Provider>
  )
}

// 自定义 Hook
export function useChatStore() {
  const context = useContext(ChatContext)
  if (!context) {
    throw new Error('useChatStore must be used within ChatProvider')
  }
  return context
}
