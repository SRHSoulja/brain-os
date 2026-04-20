// Service registry — configure for your deployment
// Add entries for services running on this machine.

const services = [
  // Local AI infrastructure
  { name: "Ollama",          type: "http-any", port: 11434, path: "/api/tags", host: "127.0.0.1", class: "infra" },
  { name: "Brain Agent",     type: "http",     port: 8798,  path: "/health",   host: "127.0.0.1", class: "infra" },
  { name: "Brain Dashboard", type: "http",     port: 8800,  path: "/health",   host: "127.0.0.1", class: "infra" },
];

module.exports = { services };
