import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { api } from '../api'

export interface Notification {
  id: string
  type: 'error' | 'warning' | 'info' | 'success'
  title: string
  message: string
  timestamp: string
  read: boolean
}

interface NotificationsContextType {
  notifications: Notification[]
  unreadCount: number
  markAsRead: (id: string) => void
  markAllAsRead: () => void
  clearAll: () => void
  checkNow: () => Promise<void>
}

const NotificationsContext = createContext<NotificationsContextType | undefined>(undefined)

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([])
  
  const unreadCount = notifications.filter(n => !n.read).length

  const checkNow = useCallback(async () => {
    try {
      // 1. Check health/stats
      const stats = await api.getStats()
      const newAlerts: Notification[] = []

      // Memory threshold check (e.g. > 1000 active nodes)
      if (stats.memory_active > 1000) {
        newAlerts.push({
          id: `mem-${Date.now()}`,
          type: 'warning',
          title: 'Memory Threshold',
          message: `Active cognitive nodes (${stats.memory_active}) exceeding optimal buffer size.`,
          timestamp: new Date().toISOString(),
          read: false
        })
      }

      // Channel disconnect check
      if (stats.channel_count === 0) {
        newAlerts.push({
          id: `chan-${Date.now()}`,
          type: 'error',
          title: 'All Channels Offline',
          message: 'Agent is currently isolated. No active communication channels found.',
          timestamp: new Date().toISOString(),
          read: false
        })
      }

      // 2. Check recent traces for errors
      const traces = await api.getTraces(5)
      traces.forEach(t => {
        if (t.status === 'error' && !notifications.some(n => n.id === t.id)) {
          newAlerts.push({
            id: t.id,
            type: 'error',
            title: `Task Failed: ${t.channel}`,
            message: t.error || 'Unknown execution error',
            timestamp: t.started_at,
            read: false
          })
        }
      })

      if (newAlerts.length > 0) {
        // Prevent duplicate spam of system alerts by comparing titles
        setNotifications(prev => {
          const uniqueNew = newAlerts.filter(na => 
            !prev.some(p => p.title === na.title && p.type === na.type && !p.read)
          )
          return [...uniqueNew, ...prev].slice(0, 50)
        })
      }
    } catch (e) {
      console.error('Failed to poll alerts', e)
    }
  }, [notifications])

  useEffect(() => {
    checkNow()
    const id = setInterval(checkNow, 30000) // Poll every 30s
    return () => clearInterval(id)
  }, [checkNow])

  const markAsRead = (id: string) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
  }

  const markAllAsRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })))
  }

  const clearAll = () => {
    setNotifications([])
  }

  return (
    <NotificationsContext.Provider value={{ 
      notifications, 
      unreadCount, 
      markAsRead, 
      markAllAsRead, 
      clearAll,
      checkNow
    }}>
      {children}
    </NotificationsContext.Provider>
  )
}

export function useNotifications() {
  const context = useContext(NotificationsContext)
  if (context === undefined) {
    throw new Error('useNotifications must be used within a NotificationsProvider')
  }
  return context
}
