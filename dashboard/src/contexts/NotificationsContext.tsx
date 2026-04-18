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
      // 1. Get backend alerts
      const backendAlerts = await api.getAlerts()
      
      // 2. Perform local heuristic checks
      const stats = await api.getStats()
      const localAlerts: Notification[] = []

      if (stats.memory_active > 1500) {
        localAlerts.push({
          id: `local-mem-${Date.now()}`,
          type: 'warning',
          title: 'High Cognitive Load',
          message: `${stats.memory_active} active nodes. Consider consolidation.`,
          timestamp: new Date().toISOString(),
          read: false
        })
      }

      // Convert backend alerts to frontend notification format
      const formattedBackend = backendAlerts.map(a => ({
        id: a.id,
        type: a.level as any,
        title: a.title,
        message: a.message,
        timestamp: a.timestamp,
        read: a.read
      }))

      // Merge and sort
      setNotifications(prev => {
        const merged = [...formattedBackend]
        // Add only unique local ones if they aren't already represented
        localAlerts.forEach(la => {
          if (!merged.some(m => m.title === la.title && !m.read)) {
            merged.push(la)
          }
        })
        return merged.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).slice(0, 100)
      })

    } catch (e) {
      console.error('Failed to poll alerts', e)
    }
  }, [])

  useEffect(() => {
    checkNow()
    const id = setInterval(checkNow, 10000) // Poll every 10s for health
    return () => clearInterval(id)
  }, [checkNow])

  const markAsRead = async (id: string) => {
    try {
      if (!id.startsWith('local-')) {
        await api.markAlertRead(id)
      }
      setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))
    } catch (e) {
      console.error('Failed to mark alert as read', e)
    }
  }

  const markAllAsRead = async () => {
    try {
      await api.markAlertRead() // Mark all on backend
      setNotifications(prev => prev.map(n => ({ ...n, read: true })))
    } catch (e) {
      console.error('Failed to mark all alerts as read', e)
    }
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
