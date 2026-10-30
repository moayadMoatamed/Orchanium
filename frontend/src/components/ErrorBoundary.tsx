import { Component, type ErrorInfo, type ReactNode } from "react";

/** One failing panel must not take the whole app down mid-run. */
export class ErrorBoundary extends Component<
  { children: ReactNode; name: string },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.name}]`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grid h-full min-h-[200px] place-items-center px-6 text-center">
        <div>
          <div className="text-[13.5px]">This panel could not be drawn.</div>
          <div className="mt-1 text-[12.5px] text-muted">
            The run itself is unaffected — other tabs still work.
          </div>
          <button
            className="btn-secondary mt-4"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
}
