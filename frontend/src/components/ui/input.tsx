import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <InputPrimitive
        ref={ref}
        type={type}
        data-slot="input"
        className={cn(
          "h-9 w-full min-w-0 rounded-xl border border-input/85 bg-background/85 px-3 py-1.5 text-base transition-all duration-200 outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground/90 focus-visible:border-primary/70 focus-visible:ring-3 focus-visible:ring-primary/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-muted/60 disabled:opacity-55 aria-invalid:border-destructive/70 aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/35 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/60 dark:aria-invalid:ring-destructive/35",
          className
        )}
        {...props}
      />
    )
  },
)

Input.displayName = "Input"

export { Input }
