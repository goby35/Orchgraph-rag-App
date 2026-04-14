import { cva } from "class-variance-authority"

/** Dùng trong Server Components cùng `cn()` — không import từ `components/ui/button`. */
export const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-xl text-sm font-medium transition-all duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 hover:scale-[1.02] active:scale-[0.98] disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-xs hover:bg-primary/92 hover:shadow-sm",
        destructive:
          "border border-destructive/25 bg-destructive/12 text-destructive hover:bg-destructive/20",
        outline:
          "border border-input/85 bg-background/90 hover:bg-accent/75 hover:text-accent-foreground",
        secondary:
          "border border-border/60 bg-secondary/85 text-secondary-foreground hover:bg-secondary",
        ghost: "hover:bg-accent/75 hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-lg px-3 text-xs",
        lg: "h-10 rounded-xl px-8",
        icon: "h-9 w-9 rounded-xl",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)
