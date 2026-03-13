# Frontend Tech Stack

## Overview

The LineupLines frontend uses a modern, minimal JavaScript stack focused on rapid development and fast iteration.

## Stack Components

### **React 19**
The primary UI library. React's component model is well-suited for data-heavy applications like draft analysis dashboards. React 19 is the latest stable version with modern features and performance improvements.

### **Vite**
Development build tool and server. Vite offers:
- Extremely fast dev server with hot module replacement (HMR)
- Much faster startup and rebuild times compared to Webpack or Create React App
- Clean proxy configuration for backend API calls (proxies `/api` and `/health` to port 8000)
- CORS-free local development

### **Tailwind CSS**
Utility-first CSS framework. Benefits:
- Rapid styling without writing separate CSS files
- Consistent design tokens and spacing
- Ideal for projects prioritizing UI iteration speed over design-system reuse
- Small final bundle size with built-in PurgeCSS

### **React Router v7**
Client-side routing for the single-page application. Handles navigation between draft views, user profiles, and other pages without full page reloads. v7 is the latest stable version (formerly integrated with Remix).

### **Axios**
HTTP client library for API communication. Chosen over `fetch` for:
- Simpler request/response interceptors
- Automatic JSON serialization/deserialization
- Built-in base URL configuration
- More concise error handling

## Design Philosophy

This stack intentionally stays **lightweight and minimal**:
- No state management library (Redux, Zustand, MobX) — React Context + hooks suffice for current scope
- No component library (Material-UI, Shadcn) — Tailwind utilities provide enough control without overhead
- No TypeScript — Keeps tooling simple; can be added later if needed

The goal is rapid iteration speed over architectural complexity, appropriate for a draft analysis tool where UI responsiveness and feature velocity matter most.

## Development Setup

See the [main CLAUDE.md](../CLAUDE.md#frontend) for development commands:
```bash
npm run dev      # Dev server on port 3000
npm run build    # Production build
npm run lint     # ESLint
```

The dev server automatically proxies API calls to the backend on port 8000, so no CORS configuration is needed locally.
