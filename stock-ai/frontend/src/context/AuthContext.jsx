import React, { createContext, useState, useEffect, useContext } from 'react'
import api from '../services/api'

const AuthContext = createContext(null)

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [loading, setLoading] = useState(true)

  // Sync token into axios default headers whenever it changes
  useEffect(() => {
    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`
      api.get('/api/auth/me')
        .then(res => setUser(res.data))
        .catch(() => _clearAuth())
        .finally(() => setLoading(false))
    } else {
      delete api.defaults.headers.common['Authorization']
      setLoading(false)
    }
  }, [token])

  const _setAuth = (access_token, userData) => {
    localStorage.setItem('token', access_token)
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
    setToken(access_token)
    setUser(userData)
  }

  const _clearAuth = () => {
    localStorage.removeItem('token')
    delete api.defaults.headers.common['Authorization']
    setToken(null)
    setUser(null)
  }

  const login = async (email, password) => {
    const res = await api.post('/api/auth/login', { email, password })
    _setAuth(res.data.access_token, res.data.user)
    return res.data
  }

  const register = async (name, email, password) => {
    const res = await api.post('/api/auth/register', { name, email, password })
    _setAuth(res.data.access_token, res.data.user)
    return res.data
  }

  const logout = () => {
    api.post('/api/auth/logout').catch(() => {})
    _clearAuth()
  }

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, loading }}>
      {!loading && children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
