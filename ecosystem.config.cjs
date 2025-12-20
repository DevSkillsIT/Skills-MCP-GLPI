/**
 * PM2 Ecosystem Configuration - MCP GLPI Server
 * Servidor MCP para integração com GLPI 10
 * 
 * Uso:
 *   pm2 start ecosystem.config.cjs
 *   pm2 restart mcp-glpi
 *   pm2 logs mcp-glpi
 */

module.exports = {
  apps: [
    {
      name: 'mcp-glpi',
      cwd: '/opt/mcp-servers/glpi',
      script: '/opt/mcp-servers/glpi/venv/bin/python',
      args: '-m uvicorn src.main:app --host 0.0.0.0 --port 8824',
      interpreter: 'none',
      
      // Environment
      env: {
        PYTHONPATH: '/opt/mcp-servers/glpi',
        PYTHONUNBUFFERED: '1',
      },
      
      // Logs
      log_file: '/opt/mcp-servers/_shared/logs/mcp-glpi-combined.log',
      out_file: '/opt/mcp-servers/_shared/logs/mcp-glpi-out.log',
      error_file: '/opt/mcp-servers/_shared/logs/mcp-glpi-error.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      merge_logs: true,
      
      // Process management
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      
      // Restart policy
      max_restarts: 10,
      min_uptime: '10s',
      restart_delay: 5000,
      
      // Health check
      listen_timeout: 10000,
      kill_timeout: 5000,
    }
  ]
};
