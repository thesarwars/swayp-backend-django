export default () => ({
  app: {
    name: process.env.APP_NAME,
    port: parseInt(process.env.PORT ?? '3000', 10),
    env: process.env.NODE_ENV,
  },
});
