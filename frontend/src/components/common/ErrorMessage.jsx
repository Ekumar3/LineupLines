export default function ErrorMessage({ message }) {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="bg-sleeper-red/10 border border-sleeper-red rounded-lg p-6 max-w-md">
        <h3 className="text-sleeper-red font-semibold mb-2">Error</h3>
        <p className="text-sleeper-gray-300">{message}</p>
      </div>
    </div>
  );
}
