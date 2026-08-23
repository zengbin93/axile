import { useCallback, useEffect, useRef, useState } from 'react'

import {
  clipboardReadFailureMessage,
  rankClipboardCandidates,
  resolveConnectionClipboardPaste,
  type ClipboardCandidate,
  type ClipboardParseContext,
} from '@/components/ui/connectionFieldClipboard'

const READING_FEEDBACK_DELAY = 200

interface Options {
  context: ClipboardParseContext
  onChange: (value: string) => void
  onCandidateCommit?: (candidate: ClipboardCandidate) => void | boolean | Promise<void | boolean>
}

/** 管理一次智能粘贴的读取、解析、选择与提交状态。 */
export function useConnectionFieldClipboard({ context, onChange, onCandidateCommit }: Options) {
  const readRequest = useRef(0)
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [pasteError, setPasteError] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<ClipboardCandidate[]>([])
  const [activeCandidate, setActiveCandidate] = useState(0)
  const [committingId, setCommittingId] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const [showReadingFeedback, setShowReadingFeedback] = useState(false)
  const rankedCandidates = rankClipboardCandidates(candidates, context)

  const clearReadingFeedback = useCallback(() => {
    if (feedbackTimer.current !== null) clearTimeout(feedbackTimer.current)
    feedbackTimer.current = null
    setReading(false)
    setShowReadingFeedback(false)
  }, [])

  const clearPasteSession = useCallback((cancelRead = true) => {
    if (cancelRead) readRequest.current += 1
    clearReadingFeedback()
    setCandidates([])
    setActiveCandidate(0)
    setCommittingId(null)
  }, [clearReadingFeedback])

  useEffect(() => {
    setPasteError(null)
    clearPasteSession()
  }, [context.clipboard?.group, context.clipboard?.role, context.kind, clearPasteSession])

  useEffect(() => () => {
    readRequest.current += 1
    if (feedbackTimer.current !== null) clearTimeout(feedbackTimer.current)
  }, [])

  useEffect(() => {
    if (activeCandidate < rankedCandidates.length) return
    setActiveCandidate(Math.max(0, rankedCandidates.length - 1))
  }, [activeCandidate, rankedCandidates.length])

  const commitCandidate = async (candidate: ClipboardCandidate) => {
    setCommittingId(candidate.id)
    try {
      const result = onCandidateCommit ? await onCandidateCommit(candidate) : undefined
      if (result === false) return false
      if (!onCandidateCommit) onChange(candidate.value)
      setPasteError(null)
      clearPasteSession(false)
      return true
    } catch (caught) {
      setPasteError(caught instanceof Error && caught.message ? caught.message : '暂时无法采用此内容')
      return false
    } finally {
      setCommittingId(null)
    }
  }

  const processClipboard = (raw: string) => {
    setCandidates([])
    setActiveCandidate(0)
    const resolution = resolveConnectionClipboardPaste(raw, context)
    if (resolution.action === 'error') {
      setPasteError(resolution.warning)
      return
    }
    setPasteError(resolution.warning ?? null)
    if (resolution.action === 'commit') {
      void commitCandidate(resolution.candidate)
      return
    }
    setCandidates(resolution.candidates)
  }

  const readClipboard = async () => {
    const request = ++readRequest.current
    setCandidates([])
    clearReadingFeedback()
    setReading(true)
    feedbackTimer.current = setTimeout(() => {
      if (request === readRequest.current) setShowReadingFeedback(true)
    }, READING_FEEDBACK_DELAY)
    try {
      if (!navigator.clipboard?.readText) throw new Error('clipboard unavailable')
      const raw = await navigator.clipboard.readText()
      if (request === readRequest.current) processClipboard(raw)
    } catch {
      if (request === readRequest.current) setPasteError(clipboardReadFailureMessage())
    } finally {
      if (request === readRequest.current) clearReadingFeedback()
    }
  }

  const paste = (raw: string) => {
    readRequest.current += 1
    clearReadingFeedback()
    processClipboard(raw)
  }

  return {
    activeCandidate,
    candidates: rankedCandidates,
    clearPasteSession,
    commitCandidate,
    committingId,
    paste,
    pasteError,
    popupOpen: rankedCandidates.length > 1,
    readClipboard,
    reading,
    setActiveCandidate,
    setPasteError,
    showReadingFeedback,
  }
}
