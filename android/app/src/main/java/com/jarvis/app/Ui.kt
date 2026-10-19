package com.jarvis.app

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** The app's light theme: colours and small view builders shared by every screen. */
object Ui {
    val bg = Color.parseColor("#F5F7FA")
    val surface = Color.WHITE
    val primary = Color.parseColor("#1565D8")
    val primarySoft = Color.parseColor("#E8F0FC")
    val text = Color.parseColor("#14202E")
    val muted = Color.parseColor("#6B7787")
    val border = Color.parseColor("#E1E6ED")
    val green = Color.parseColor("#1E9E5A")
    val warn = Color.parseColor("#9A5B00")
    val warnSoft = Color.parseColor("#FFF4E0")

    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()

    fun rounded(fill: Int, radiusDp: Int, context: Context, stroke: Int? = null) = GradientDrawable().apply {
        setColor(fill)
        cornerRadius = dp(context, radiusDp).toFloat()
        stroke?.let { setStroke(dp(context, 1), it) }
    }

    fun oval(fill: Int, context: Context, stroke: Int? = null) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL
        setColor(fill)
        stroke?.let { setStroke(dp(context, 1), it) }
    }

    /** Sets the screen and keeps it clear of the status bar, gesture bar and keyboard
     *  (Android 15 draws apps edge to edge). */
    fun show(activity: Activity, root: View, padH: Int = 16, padV: Int = 12) {
        val h = dp(activity, padH)
        val v = dp(activity, padV)
        root.setBackgroundColor(bg)
        root.setOnApplyWindowInsetsListener { view, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                view.setPadding(h + bars.left, v + bars.top, h + bars.right, v + bars.bottom)
            } else {
                @Suppress("DEPRECATION")
                view.setPadding(h + insets.systemWindowInsetLeft, v + insets.systemWindowInsetTop,
                    h + insets.systemWindowInsetRight, v + insets.systemWindowInsetBottom)
            }
            insets
        }
        activity.setContentView(root)
        root.requestApplyInsets()
    }

    fun column(context: Context) = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }

    fun row(context: Context) = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun text(context: Context, value: String, sizeSp: Float = 15f, color: Int = text, bold: Boolean = false) =
        TextView(context).apply {
            this.text = value
            textSize = sizeSp
            setTextColor(color)
            if (bold) typeface = Typeface.DEFAULT_BOLD
            setLineSpacing(0f, 1.15f)
        }

    /** Filled blue button (main action). */
    fun primaryButton(context: Context, label: String, onClick: () -> Unit) = Button(context).apply {
        text = label
        isAllCaps = false
        textSize = 15f
        setTextColor(Color.WHITE)
        background = rounded(primary, 12, context)
        stateListAnimator = null
        setPadding(dp(context, 18), dp(context, 12), dp(context, 18), dp(context, 12))
        setOnClickListener { onClick() }
    }

    /** Light outlined button (secondary action). */
    fun softButton(context: Context, label: String, onClick: () -> Unit) = Button(context).apply {
        text = label
        isAllCaps = false
        textSize = 14f
        setTextColor(primary)
        background = rounded(primarySoft, 12, context)
        stateListAnimator = null
        minHeight = 0
        minimumHeight = 0
        setPadding(dp(context, 14), dp(context, 8), dp(context, 14), dp(context, 8))
        setOnClickListener { onClick() }
    }

    /** Round icon button, e.g. 🎤 or ⚙. */
    fun iconButton(context: Context, icon: String, sizeDp: Int, filled: Boolean, onClick: () -> Unit) = TextView(context).apply {
        text = icon
        textSize = if (sizeDp >= 50) 22f else 18f
        gravity = Gravity.CENTER
        setTextColor(if (filled) Color.WHITE else primary)
        background = if (filled) oval(primary, context) else oval(surface, context, border)
        layoutParams = LinearLayout.LayoutParams(dp(context, sizeDp), dp(context, sizeDp))
        isClickable = true
        isFocusable = true
        setOnClickListener { onClick() }
    }

    fun field(context: Context, hint: String, value: String = "") = EditText(context).apply {
        this.hint = hint
        setText(value)
        textSize = 16f
        setTextColor(this@Ui.text)
        setHintTextColor(muted)
        isSingleLine = true
        background = rounded(surface, 12, context, border)
        setPadding(dp(context, 14), dp(context, 12), dp(context, 14), dp(context, 12))
    }

    fun card(context: Context) = column(context).apply {
        background = rounded(surface, 16, context, border)
        setPadding(dp(context, 16), dp(context, 12), dp(context, 16), dp(context, 12))
    }

    fun matchWrap(topMarginDp: Int = 0, context: Context) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(context, topMarginDp) }
}
