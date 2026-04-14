import * as React from "react"

import { cn } from "@/lib/utils"

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        data-slot="textarea"
        className={cn(
          "flex field-sizing-content min-h-16 w-full rounded-xl border border-input/85 bg-background/85 px-3 py-2 text-base transition-all duration-200 outline-none placeholder:text-muted-foreground/90 focus-visible:border-primary/70 focus-visible:ring-3 focus-visible:ring-primary/20 disabled:cursor-not-allowed disabled:bg-muted/60 disabled:opacity-55 aria-invalid:border-destructive/70 aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/35 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/60 dark:aria-invalid:ring-destructive/35",
          className
        )}
        {...props}
      />
    )
  },
)

Textarea.displayName = "Textarea"

export { Textarea }
