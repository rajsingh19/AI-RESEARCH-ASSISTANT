import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, Link } from 'react-router-dom';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await login(email, password);
      navigate('/chat');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid login details');
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: '#1a1a1a', color: '#fff', fontFamily: 'sans-serif' }}>
      <form onSubmit={handleSubmit} style={{ width: '100%', maxWidth: '400px', padding: '40px', background: '#2d2d2d', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
        <h2 style={{ marginBottom: '24px', textAlign: 'center' }}>Welcome Back</h2>
        {error && <div style={{ color: '#ff4d4d', marginBottom: '16px', fontSize: '14px' }}>{error}</div>}
        <div style={{ marginBottom: '16px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>Email</label>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: '4px', border: '1px solid #444', backgroundColor: '#1a1a1a', color: '#fff', boxSizing: 'border-box' }} />
        </div>
        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px' }}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} required style={{ width: '100%', padding: '10px', borderRadius: '4px', border: '1px solid #444', backgroundColor: '#1a1a1a', color: '#fff', boxSizing: 'border-box' }} />
        </div>
        <button type="submit" style={{ width: '100%', padding: '12px', borderRadius: '4px', border: 'none', backgroundColor: '#007acc', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}>Log In</button>
        <p style={{ marginTop: '16px', fontSize: '14px', textAlign: 'center', color: '#aaa' }}>Don't have an account? <Link to="/register" style={{ color: '#007acc', textDecoration: 'none' }}>Register</Link></p>
      </form>
    </div>
  );
};

export default Login;