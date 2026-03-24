import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types'

interface ChatBubbleProps {
  message: ChatMessage
}

export default function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3 mb-4', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div className={cn(
        'w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-semibold',
        isUser
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted text-muted-foreground border',
      )}>
        {isUser ? 'U' : 'AI'}
      </div>

      {/* Bubble */}
      <div className={cn(
        'max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words',
        isUser
          ? 'bg-primary text-primary-foreground rounded-tr-sm'
          : 'bg-muted rounded-tl-sm',
      )}>
        {message.content}
        {/* Blinking cursor khi đang stream */}
        {message.streaming && (
          <span className="inline-block w-0.5 h-4 bg-current ml-1 align-middle animate-pulse" />
        )}
      </div>
    </div>
  )
}